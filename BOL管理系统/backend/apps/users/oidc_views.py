# -*- coding: utf-8 -*-
"""OIDC (Keycloak) 认证 API 视图 (方案文档第 6 章)

端点 (挂入 auth_urls.py, 前缀 /api/auth):
- GET  /config           登录页功能开关 (OIDC/本地登录/自助注册/密码自助, 公开)
- GET  /oidc/login       跳转 Keycloak 授权 (302)
- GET  /oidc/callback    Keycloak 授权回调 → AuthToken + 一次性码 → 302 前端
- POST /oidc/token       一次性码 (otk) 换本地登录态 (响应结构与本地登录一致)

OIDC 流程 (与 MSIA 同构):
  前端点"统一身份登录" → GET /api/auth/oidc/login → 302 Keycloak 授权页
  → 用户认证 → 302 /api/auth/oidc/callback?code=&state=
  → 校验 state/nonce/PKCE, 换 id_token, 解析身份 (resolve_or_create)
  → AuthToken(source='oidc') + 60s 一次性码 → 302 前端 /oidc/callback?otk=...
  → 前端 POST /api/auth/oidc/token 换登录态 (复用 _build_login_response)

用户匹配 (方案文档 6.1):
  1. groups 准入校验 (id_token groups claim 必含 app-bol)
  2. 跨库查中央对照表 CN_AME.dbo.CN_AME_SSO_UserMap (system_code='bol')
  3. 回落 preferred_username 作为本地用户名
  4. 本地 Employee 表 (CN_IE_BOL_Employee) 命中 → 直接登录
  5. 未命中且允许自动建档 → 按最低权限 (VIEWER) 创建本地账号
"""
import logging
import secrets
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, connections
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users import oidc
from apps.users.auth_views import _build_login_response
from apps.users.models import AuthToken, Employee

logger = logging.getLogger(__name__)

# 中央对照表查询: 本地用户名映射 (命中则用映射值, 未命中回落 preferred_username)
# BOL 连接在 CMC 库, 与 CN_AME 同实例, 三段名直接跨库只读 (T01 已授权 sparePartRead)
#
# 大小写不敏感: 两侧都套 UPPER() 后再比较, 与库/列排序规则 (CI 或 _CS_) 无关,
# 也不写死任何 COLLATE。历史账号 (Yaolei / Zhangy4) 在 _CS_ 规则下也能被命中,
# 避免"查不到 → 自动建档 → 同一人两条记录"。
_USERMAP_SQL = (
    "SELECT m.local_username "
    "FROM CN_AME.dbo.CN_AME_SSO_UserMap m "
    "JOIN CN_AME.dbo.CN_AME_SSO_User u ON u.employee_no = m.employee_no "
    "WHERE m.system_code = %s "
    "AND UPPER(LTRIM(RTRIM(u.login_name))) = UPPER(LTRIM(RTRIM(%s)))"
)


def _find_employee(username):
    """忽略大小写查本地员工 (Django __iexact, 与排序规则无关)"""
    return Employee.objects.filter(username__iexact=username).first()


def _apply_claims(employee, preferred_username, claims):
    """命中既有账号: 状态校验 + 资料补充 (两条命中路径共用)"""
    if employee.status != "ACTIVE":
        logger.warning(
            "OIDC 登录被拒 (账号禁用): %s (local=%s)", preferred_username, employee.username,
        )
        raise PermissionDenied("账号已禁用, 请联系管理员")
    changed = []
    if not employee.email and claims.get("email"):
        employee.email = claims["email"]
        changed.append("email")
    if not employee.name and claims.get("name"):
        employee.name = claims["name"]
        changed.append("name")
    if changed:
        employee.save(update_fields=changed + ["updated_at"])
        logger.info("OIDC 登录资料补充: %s (%s)", employee.username, "/".join(changed))
    return employee


def resolve_or_create(preferred_username, groups, claims):
    """解析 OIDC 身份 → 返回本地 Employee 对象 (方案文档 6.1)

    Args:
        preferred_username: Keycloak 用户名 (= 中央表 login_name, 小写)
        groups: id_token 的 groups claim
        claims: id_token 全部声明 (name/email 等)

    Returns:
        Employee: 本地员工对象 (status='ACTIVE')

    Raises:
        PermissionDenied: 未开通本系统 / 账号已禁用 / 账号不存在且不允许自动建档
    """
    # 保留原始大小写 (建档时按原样存库); 所有比对均忽略大小写,
    # 兼容库排序规则为 _CS_ 的历史环境 (原先强制 lower 会让 "Yaolei" 永远查不到)
    preferred_username = (preferred_username or "").strip()
    if not preferred_username:
        raise PermissionDenied("登录信息不完整 (缺少用户名), 请联系管理员")

    # 1. 准入组校验 (groups claim 不含 app-bol → 未开通本系统)
    groups = groups or []
    if settings.OIDC_REQUIRED_GROUP not in groups:
        logger.warning(
            "OIDC 准入校验失败: user=%s, groups=%s, required=%s",
            preferred_username, groups, settings.OIDC_REQUIRED_GROUP,
        )
        raise PermissionDenied("未开通本系统访问权限，请联系管理员")

    # 2. 跨库查中央对照表 (本地用户名映射)
    with connections["default"].cursor() as cursor:
        cursor.execute(_USERMAP_SQL, ["bol", preferred_username])
        row = cursor.fetchone()
    local_username = str(row[0]).strip() if row and row[0] else preferred_username
    if row:
        logger.info(
            "OIDC 身份解析: %s 命中 UserMap 映射 -> 本地用户名 %s",
            preferred_username, local_username,
        )
    else:
        logger.info("OIDC 身份解析: %s 无 UserMap 映射, 回落 preferred_username", preferred_username)

    # 3. 本地员工表查询 (username 唯一; __iexact 忽略大小写)
    employee = _find_employee(local_username)

    # 4. 命中: 状态校验 + 资料补充
    if employee:
        return _apply_claims(employee, preferred_username, claims)

    # 5. 未命中: 自动建档 (最低权限 VIEWER) 或拒绝
    if not settings.OIDC_AUTO_CREATE_USER:
        logger.warning("OIDC 登录被拒 (账号不存在且禁止自动建档): %s", local_username)
        raise PermissionDenied("账号不存在, 请联系管理员开通")

    # 5.1 建档前查重 (忽略大小写): 即使步骤 3 因排序规则没命中, 这里也必须再查一次;
    # 命中则复用既有账号, 绝不新建 (否则同一人在 _CS_ 库下会出现两条记录)
    duplicate = _find_employee(local_username)
    if duplicate:
        logger.info(
            "OIDC 自动建档前查重命中 (大小写差异命中): kc=%s local=%s -> 复用既有账号, 不新建",
            preferred_username, duplicate.username,
        )
        return _apply_claims(duplicate, preferred_username, claims)

    # 建档用户名取解析出的本地用户名并保留原样大小写 (不再强制 lower):
    # 若 UserMap 存在映射 (kc_name -> local_name), 用 local_name 建档可保证
    # 下次登录解析路径稳定; 无映射时即 preferred_username 原值。
    logger.info("OIDC 自动建档: %s (role=VIEWER, source=oidc)", local_username)
    employee = Employee(
        username=local_username,
        name=(claims.get("name") or "").strip() or local_username,
        email=(claims.get("email") or "").strip(),
        role="VIEWER",  # 最低权限
        status="ACTIVE",
        password="",  # 不设本地密码, 密码生命周期归 Keycloak
        must_change_password=False,  # OIDC 用户无本地密码, 不强制改密
    )
    try:
        employee.save()
    except IntegrityError:
        # 唯一索引冲突 (并发登录 / 库为 CI 排序规则时 "Yaolei" 与 "yaolei" 撞车):
        # 回查既有账号并复用, 不让异常冒泡成 500, 也不再建第二条
        logger.warning(
            "OIDC 自动建档撞唯一索引, 回查既有账号: %s", local_username,
        )
        existing = _find_employee(local_username)
        if existing is None:
            raise
        logger.info("OIDC 自动建档冲突后复用既有账号: %s", existing.username)
        return _apply_claims(existing, preferred_username, claims)
    return employee


class AuthConfigView(APIView):
    """登录页功能开关 (公开)

    前端据此显示/隐藏 OIDC 入口、本地登录表单、注册入口、密码自助入口。
    拉取失败时前端按全 false 处理 (仅游客通道可用)。
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "oidc_enabled": settings.OIDC_ENABLED,
            "local_auth_enabled": settings.LOCAL_AUTH_ENABLED,
            "self_registration_enabled": settings.SELF_REGISTRATION_ENABLED,
            "password_self_service_enabled": settings.PASSWORD_SELF_SERVICE_ENABLED,
        })


def oidc_login(request):
    """生成 state/nonce/PKCE 并 302 到 Keycloak 授权端点

    state/nonce/verifier 存内存 (TTL 10min, 单次消费)。
    Keycloak 未启用 (OIDC_ENABLED=false) 时返回 503。
    """
    # 配置体检 (fail loud): 关闭态只记一条 info; 启用态配置不完整直接 503 + 可读提示,
    # 不拿坏值去拼授权 URL
    problems = oidc.validate_config()
    oidc.log_config_problems(problems)
    if not settings.OIDC_ENABLED:
        return HttpResponse("统一登录未启用", status=503)

    if problems["errors"]:
        return HttpResponse(
            "OIDC 配置不完整: " + "；".join(problems["errors"]), status=503,
        )

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = oidc.create_pkce_pair()
    oidc.store_oidc_session(state, nonce, verifier)
    logger.info("OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)")
    return HttpResponseRedirect(oidc.build_authorize_url(state, nonce, challenge))


def oidc_callback(request):
    """Keycloak 授权回调: 换 token → 验签 → 解析身份 → AuthToken + 一次性码

    成功: 302 前端回调页 {OIDC_FRONT_CALLBACK}?otk=<60s 一次性码>
    失败 (403 类/授权异常): 302 前端回调页 {OIDC_FRONT_CALLBACK}?error=<中文提示>
    state 无效: 400 (不可信回调, 不回前端)
    """
    # 双轨期: OIDC 关闭时回调一律不受理 (不走身份解析/自动建档)
    if not settings.OIDC_ENABLED:
        return HttpResponse("统一登录未启用", status=503)

    front = settings.OIDC_FRONT_CALLBACK

    def _redirect_error(msg):
        """失败统一回前端回调页展示 (URL 只放简短中文提示, 技术细节进日志)"""
        logger.warning("OIDC 回调失败: %s", msg)
        return HttpResponseRedirect("{}?error={}".format(front, quote(msg)))

    # Keycloak 侧错误 (用户拒绝授权 / 客户端配置错误等)
    error = request.GET.get("error")
    if error:
        return _redirect_error(request.GET.get("error_description") or "统一登录被取消或失败，请重试")

    # state 校验 (消费式, 防重放/CSRF; 不匹配按不可信回调处理 → 400)
    state = request.GET.get("state")
    if not state:
        return HttpResponseBadRequest("登录状态无效，请重试")
    try:
        oidc_session = oidc.consume_oidc_session(state)
    except KeyError:
        return HttpResponseBadRequest("登录状态无效，请重试")

    code = request.GET.get("code")
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
        employee = resolve_or_create(preferred_username, groups, claims)
    except PermissionDenied as e:
        return _redirect_error(str(e.detail))
    except Exception:
        logger.exception("OIDC 身份解析异常")
        return _redirect_error("登录处理异常，请联系管理员")

    # 签发本地 AuthToken (source='oidc') + 60s 一次性码
    # 令牌复用策略与本地登录一致 (create_for_employee 复用未过期令牌),
    # 仅来源标记为 oidc, 切换日 DELETE source='local' 作废旧本地令牌
    expire_hours = getattr(settings, "AUTH_TOKEN_EXPIRE_HOURS", 168)
    token = AuthToken.create_for_employee(employee, expire_hours=expire_hours, source="oidc")
    employee.last_login = timezone.now()
    employee.save(update_fields=["last_login"])
    otk = oidc.create_otk(employee.id, token.key)
    logger.info("OIDC 登录成功: %s (employee id=%s)", preferred_username, employee.id)
    return HttpResponseRedirect("{}?otk={}".format(front, otk))


class OidcTokenView(APIView):
    """用 OIDC 回调下发的一次性码 (otk) 换取本地登录态

    响应结构与本地登录 (POST /login) 完全一致, 前端无感切换。
    otk 60s 有效且单次消费; 无效/过期返回 400。
    """
    permission_classes = [AllowAny]

    def post(self, request):
        otk = (request.data.get("otk") or "").strip()
        if not otk:
            return Response({"detail": "缺少登录凭证"}, status=400)

        try:
            data = oidc.consume_otk(otk)
        except oidc.OtkError:
            return Response({"detail": "登录凭证无效或已过期，请重新登录"}, status=400)

        # 换取前账号被禁用/删除 → 凭证作废
        try:
            auth_token = AuthToken.objects.select_related("employee").get(key=data["token"])
        except AuthToken.DoesNotExist:
            return Response({"detail": "登录凭证已失效，请重新登录"}, status=400)

        employee = auth_token.employee
        if employee.id != data["employee_id"] or employee.status != "ACTIVE":
            return Response({"detail": "登录凭证已失效，请重新登录"}, status=400)

        return Response(_build_login_response(employee, auth_token))
