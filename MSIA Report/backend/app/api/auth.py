"""认证路由

端点:
- GET  /api/auth/config           登录页配置 (OIDC/本地开关, 公开)
- POST /api/auth/login            本地账密登录 (LOCAL_LOGIN_ENABLED 开关控制)
- GET  /api/auth/oidc/login       跳转 Keycloak 授权 (302)
- GET  /api/auth/oidc/callback    Keycloak 授权回调 → 本地 JWT + 一次性码
- POST /api/auth/oidc/token       一次性码 (otk) 换本地 JWT
- POST /api/auth/logout           退出登录
- GET  /api/auth/me               当前用户信息

OIDC 流程 (方案文档第 5 章):
  前端点"统一身份登录" → GET /api/auth/oidc/login → 302 Keycloak 授权页
  → 用户认证 → 302 /api/auth/oidc/callback?code=&state=
  → 校验 state/nonce/PKCE, 换 id_token, 解析身份 (sso_identity)
  → 签本地 JWT + 60s 一次性码 → 302 前端 /oidc/callback?otk=...
  → 前端 POST /api/auth/oidc/token 换登录态 (与本地登录响应结构一致)
"""
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.core import oidc
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, OtkExchangeRequest, TokenResponse, UserOut
from app.services.sso_identity import resolve_or_create
from app.utils.time import now_cst

# HR 同步用户的默认初始密码
DEFAULT_PASSWORD = "Inalfa2026"

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.get("/config", summary="获取登录配置 (公开)")
def auth_config():
    """登录页据此显示/隐藏 OIDC 入口与本地登录表单

    无需登录; 前端拉取失败时按全 false 处理 (不显示 OIDC, 不显示本地表单)。
    """
    return {
        "oidc_enabled": settings.OIDC_ENABLED,
        "local_login_enabled": settings.LOCAL_LOGIN_ENABLED,
    }


@router.post("/login", response_model=TokenResponse, summary="用户登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """用户名密码登录, 返回 JWT 令牌

    - HR 同步用户初始无密码, 可用默认密码 Inalfa2026 首次登录
    - 首次登录后自动将默认密码哈希写入数据库
    - P4 单轨期 LOCAL_LOGIN_ENABLED=false 时本端点返回 403
    """
    # P4 单轨开关: 本地登录关闭后统一走 Keycloak (方案文档 8.1 开关矩阵)
    if not settings.LOCAL_LOGIN_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="本地登录已关闭，请使用统一身份登录",
        )

    user = (
        db.query(User)
        .filter(User.Username == payload.username, User.IsDeleted == False)  # noqa: E712
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.Status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用, 请联系管理员",
        )

    # 密码校验
    if user.PasswordHash:
        # 已设置密码, 正常校验
        if not verify_password(payload.password, user.PasswordHash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
    else:
        # 未设置密码 (HR 同步用户), 校验默认密码并写入哈希
        if payload.password != DEFAULT_PASSWORD:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
        # 首次登录, 将默认密码哈希写入数据库
        user.PasswordHash = hash_password(payload.password)
        user.PasswordUpdatedAt = now_cst()
        db.commit()

    token = create_access_token(str(user.Id), user.Role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut.model_validate(user, from_attributes=True),
    )


@router.get("/oidc/login", summary="跳转统一身份登录 (Keycloak)")
def oidc_login():
    """生成 state/nonce/PKCE 并 302 到 Keycloak 授权端点

    state/nonce/verifier 存内存 (TTL 10min, 单次消费)。
    Keycloak 未启用 (OIDC_ENABLED=false) 时返回 503。
    """
    # 配置体检 (fail loud): 关闭态只记一条 info; 启用态配置不完整直接 503 + 可读提示,
    # 不拿坏值去拼授权 URL
    problems = oidc.validate_config()
    oidc.log_config_problems(problems)
    if not settings.OIDC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="统一登录未启用",
        )

    if problems["errors"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC 配置不完整: " + "；".join(problems["errors"]),
        )

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = oidc.create_pkce_pair()
    oidc.store_oidc_session(state, nonce, verifier)
    logger.info("OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)")
    # 302 与 BOL 系统口径一致 (T05-R1 #10); RedirectResponse 默认 307
    return RedirectResponse(oidc.build_authorize_url(state, nonce, challenge), status_code=302)


@router.get("/oidc/callback", summary="OIDC 授权回调 (Keycloak)")
def oidc_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db),
):
    """Keycloak 授权回调: 换 token → 验签 → 解析身份 → 本地 JWT + 一次性码

    成功: 302 前端回调页 {OIDC_FRONT_CALLBACK}?otk=<60s 一次性码>
    失败 (403 类/授权异常): 302 前端回调页 {OIDC_FRONT_CALLBACK}?error=<中文提示>
    state 无效: 400 (不可信回调, 不回前端)
    """
    # 双轨期: OIDC 关闭时回调一律不受理 (不走身份解析/自动建档)
    if not settings.OIDC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="统一登录未启用",
        )

    front = settings.OIDC_FRONT_CALLBACK

    def _redirect_error(msg: str) -> RedirectResponse:
        """失败统一回前端回调页展示 (URL 只放简短中文提示, 技术细节进日志)"""
        logger.warning("OIDC 回调失败: {}", msg)
        return RedirectResponse("{}?error={}".format(front, quote(msg)), status_code=302)

    # Keycloak 侧错误 (用户拒绝授权 / 客户端配置错误等)
    if error:
        return _redirect_error(error_description or "统一登录被取消或失败，请重试")

    # state 校验 (消费式, 防重放/CSRF; 不匹配按不可信回调处理 → 400)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登录状态无效，请重试",
        )
    try:
        oidc_session = oidc.consume_oidc_session(state)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登录状态无效，请重试",
        )

    if not code:
        return _redirect_error("授权失败：未收到授权码，请重试")

    # 授权码换 token + 验签 (失败多为网络/配置问题, 回前端提示重试)
    try:
        token_data = oidc.exchange_code(code, oidc_session["code_verifier"])
        id_token = token_data.get("id_token")
        if not id_token:
            raise ValueError("token 响应缺少 id_token")
        claims = oidc.verify_id_token(id_token, oidc_session["nonce"])
    except Exception:
        logger.exception("OIDC token 交换/验签失败")
        return _redirect_error("统一登录验证失败，请重试或联系管理员")

    preferred_username = claims.get("preferred_username") or ""
    groups = claims.get("groups") or []
    if isinstance(groups, str):  # 极端情况 groups claim 为字符串, 统一成列表
        groups = [groups]

    # 身份解析 (403 类: 未开通/禁用/不存在 → 回前端展示)
    try:
        user = resolve_or_create(db, preferred_username, groups, claims)
    except HTTPException as e:
        return _redirect_error(str(e.detail))
    except Exception:
        logger.exception("OIDC 身份解析异常")
        return _redirect_error("登录处理异常，请联系管理员")

    # 签本地 JWT + 60s 一次性码 (token 不落 URL, 前端凭 otk 换登录态)
    token = create_access_token(str(user.Id), user.Role)
    otk = oidc.create_otk(user.Id, token)
    logger.info("OIDC 登录成功: {} (local user id={})", preferred_username, user.Id)
    return RedirectResponse("{}?otk={}".format(front, otk), status_code=302)


@router.post("/oidc/token", response_model=TokenResponse, summary="一次性码换本地 JWT")
def oidc_token(payload: OtkExchangeRequest, db: Session = Depends(get_db)):
    """用 OIDC 回调下发的一次性码 (otk) 换取本地登录态

    响应结构与本地登录 (POST /login) 完全一致, 前端无感切换。
    otk 60s 有效且单次消费; 无效/过期返回 400。
    """
    try:
        data = oidc.consume_otk(payload.otk)
    except oidc.OtkError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登录凭证无效或已过期，请重新登录",
        )

    user = (
        db.query(User)
        .filter(User.Id == data["user_id"], User.IsDeleted == False)  # noqa: E712
        .first()
    )
    if not user or user.Status != 1:
        # 换取前账号被禁用/删除 → 凭证作废
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登录凭证已失效，请重新登录",
        )

    return TokenResponse(
        access_token=data["token"],
        token_type="bearer",
        user=UserOut.model_validate(user, from_attributes=True),
    )


@router.post("/logout", summary="退出登录")
def logout(current: User = Depends(get_current_user)):
    """退出登录 (JWT 无服务端状态, 仅作记录)

    注意: 此处仅清本地会话; Keycloak 侧 SSO 会话的全局登出传播
    (front-channel logout) 为方案文档 5.1 范围外, 本期不做。
    """
    return {"message": "已退出登录", "user": current.Username}


@router.get("/me", response_model=UserOut, summary="获取当前用户")
def me(current: User = Depends(get_current_user)):
    """返回当前登录用户信息"""
    return current
