"""SSO 身份解析与自动建档 (方案文档 5.1)

匹配约定 (方案文档 9 共享约定, 两系统一致):
  1. groups 准入校验 (token groups claim 必含 required_group)
  2. CN_AME_SSO_UserMap(system_code='msia') 查本地用户名映射
  3. 回落 preferred_username
  4. 本地用户表 (CN_AME_MISA_User) 命中 → 直接登录
  5. 未命中且允许自动建档 → 按最低权限 (reviewee) 创建本地账号

SSO 五表无 ORM 模型 (T01 建在 CN_AME, 与业务表同库), 走原生 SQL 查询。
"""
from typing import Any, Dict, List

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User

# 中央对照表查询: 本地用户名映射 (命中则用映射值, 未命中回落 preferred_username)
# 大小写不敏感: 两侧都套 UPPER() 后再比较, 与库/列排序规则 (CI 或 _CS_) 无关,
# 也不写死任何 COLLATE。原生 SQL 无法使用 Django 的 __iexact, 故用 UPPER() 等价写法。
_USERMAP_SQL = text(
    """
    SELECT m.local_username
    FROM dbo.CN_AME_SSO_UserMap m
    JOIN dbo.CN_AME_SSO_User u ON u.employee_no = m.employee_no
    WHERE m.system_code = 'msia'
      AND UPPER(LTRIM(RTRIM(u.login_name))) = UPPER(LTRIM(RTRIM(:login_name)))
    """
)


def _find_user(db: Session, username: str):
    """忽略大小写查本地用户 (UPPER() 表达式, 与排序规则无关, 不用 ORM 的 iexact)"""
    return (
        db.query(User)
        .filter(
            func.upper(User.Username) == func.upper(username),
            User.IsDeleted == False,  # noqa: E712
        )
        .first()
    )


def _apply_claims(db: Session, user: User, preferred_username: str, claims: Dict[str, Any]):
    """命中既有账号: 状态校验 + 资料补充 (两条命中路径共用)"""
    if user.Status != 1:
        logger.warning("OIDC 登录被拒 (账号禁用): {} (local={})", preferred_username, user.Username)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已禁用, 请联系管理员",
        )
    changed = False
    if not user.Email and claims.get("email"):
        user.Email = claims.get("email")
        changed = True
    if not user.DisplayName and claims.get("name"):
        user.DisplayName = claims.get("name")
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
        logger.info("OIDC 登录资料补充: {} (Email/DisplayName)", user.Username)
    return user


def resolve_or_create(
    db: Session,
    preferred_username: str,
    groups: List[str],
    claims: Dict[str, Any],
) -> User:
    """解析 OIDC 身份 → 返回本地 User 对象

    Args:
        db: 数据库会话 (CN_AME, 与 MSIA 业务表同库)
        preferred_username: Keycloak 用户名 (= 中央表 login_name, 小写)
        groups: id_token 的 groups claim
        claims: id_token 全部声明 (name/email 等)

    Raises:
        HTTPException 403: 未开通权限 / 账号已禁用 / 账号不存在且不允许自动建档
    """
    # 保留原始大小写 (建档时按原样存库); 所有比对均忽略大小写, 兼容库排序规则为 _CS_
    # 的历史环境 (原先强制 lower 会让 "Yaolei" / "Zhangy4" 永远查不到 → 重复建档)
    preferred_username = (preferred_username or "").strip()
    if not preferred_username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="登录信息不完整 (缺少用户名), 请联系管理员",
        )

    # 1. 准入组校验 (groups claim 不含 required_group → 未开通本系统)
    groups = groups or []
    if settings.OIDC_REQUIRED_GROUP not in groups:
        logger.warning(
            "OIDC 准入校验失败: user={}, groups={}, required={}",
            preferred_username, groups, settings.OIDC_REQUIRED_GROUP,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="未开通本系统访问权限，请联系管理员",
        )

    # 2. 查中央对照表 (本地用户名映射; SQL 内 UPPER() 比对, 忽略大小写)
    row = db.execute(_USERMAP_SQL, {"login_name": preferred_username}).first()
    local_username = str(row[0]).strip() if row and row[0] else preferred_username
    if row:
        logger.info(
            "OIDC 身份解析: {} 命中 UserMap 映射 -> 本地用户名 {}",
            preferred_username, local_username,
        )
    else:
        logger.info("OIDC 身份解析: {} 无 UserMap 映射, 回落 preferred_username", preferred_username)

    # 3. 本地用户表查询 (Username 唯一, IsDeleted=False; UPPER() 忽略大小写)
    user = _find_user(db, local_username)

    # 4. 命中: 状态校验 + 资料补充
    if user:
        return _apply_claims(db, user, preferred_username, claims)

    # 5. 未命中: 自动建档 (最低权限) 或拒绝
    if not settings.OIDC_AUTO_CREATE_USER:
        logger.warning("OIDC 登录被拒 (账号不存在且禁止自动建档): {}", local_username)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号不存在, 请联系管理员开通",
        )

    # 5.1 建档前查重 (忽略大小写): 即使步骤 3 因排序规则没命中, 这里也必须再查一次;
    # 命中则复用既有账号, 绝不新建 (否则同一人在 _CS_ 库下会出现两条记录)
    duplicate = _find_user(db, local_username)
    if duplicate:
        logger.info(
            "OIDC 自动建档前查重命中 (大小写差异命中): kc={} local={} -> 复用既有账号, 不新建",
            preferred_username, duplicate.Username,
        )
        return _apply_claims(db, duplicate, preferred_username, claims)

    # 建档用户名与本地查询口径一致: 用映射后的 local_username, 并保留原样大小写
    # (T05-R1 #2 修复, 与 BOL 系统口径对齐)。原实现用 preferred_username,
    # 未来配置 UserMap 映射 (login_name != local_username) 时, 自动建档账号会与
    # 映射值分叉/撞唯一约束。
    logger.info("OIDC 自动建档: {} (local={}, role=reviewee)", preferred_username, local_username)
    user = User(
        Username=local_username,
        DisplayName=claims.get("name") or preferred_username,
        Email=claims.get("email"),
        PasswordHash=None,  # 不设本地密码, 密码生命周期归 Keycloak
        Role="reviewee",  # 最低权限
        Status=1,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 唯一索引冲突 (并发登录 / 库为 CI 排序规则时 "Yaolei" 与 "yaolei" 撞车):
        # 回滚后回查既有账号并复用, 不让异常冒泡成 500, 也不再建第二条
        db.rollback()
        logger.warning("OIDC 自动建档撞唯一索引, 回查既有账号: {}", local_username)
        existing = _find_user(db, local_username)
        if existing is None:
            raise
        logger.info("OIDC 自动建档冲突后复用既有账号: {}", existing.Username)
        return _apply_claims(db, existing, preferred_username, claims)
    db.refresh(user)
    return user
