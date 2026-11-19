"""SSO 中央表派生同步 (T05-R1 #7, 方案文档 5.2 / 9 共享约定)

从 SSO 中央表 CN_AME_SSO_User (仅 ~13 人) 派生更新本地 CN_AME_MISA_User:
  - 按 Username = login_name 匹配本地用户 (SQL Server 排序规则不区分大小写)
  - 命中: 更新 DisplayName / Email / Status (仅有变化时写库)
  - 未命中: 跳过 —— 绝不新建 (建档由 OIDC 首次登录自动完成, 见 sso_identity)
  - 本地存在但中央表未覆盖的用户: 绝不触碰

安全边界 (与 HRDB 全量同步的本质区别):
  本地 ~4275 个用户来自 HRDB fine_user 同步, 中央表只覆盖 SSO 已纳管人员;
  若按"中央表缺失即禁用"的口径批量禁用未命中用户, 属重大事故。
  本服务在结构上排除该可能: 只遍历中央表行, 永不遍历本地全表。

中央表 status 语义: 1=在职, 0=停用 (与 BOL sync_sso_status 一致)。
停用传导到本地 Status=0 后, OIDC 登录入口即拒绝 (sso_identity 状态校验)。

由调度器每日 06:30 调用 (gated by SSO_USER_SYNC_ENABLED, config.ini [security])。
"""
from typing import Dict

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import User

# 中央表全量读取 (仅 ~13 行; 不 JOIN UserMap —— MSIA 自动建档口径即 login_name,
# 见 sso_identity.resolve_or_create, T05-R1 #2)
_CENTRAL_SQL = text(
    """
    SELECT u.login_name, u.display_name, u.email, u.status
    FROM dbo.CN_AME_SSO_User u
    ORDER BY u.login_name
    """
)

# 中央表 status 语义 (与 BOL sync_sso_status / MSIA User.Status 一致): 1=启用, 0=禁用
_CENTRAL_ACTIVE = 1
_CENTRAL_INACTIVE = 0


def sync_from_sso_central(db: Session) -> Dict[str, int]:
    """执行一次 SSO 中央表派生同步

    Args:
        db: 主数据库会话 (CN_AME, 中央表与业务表同库)

    Returns:
        统计 dict:
          central_read        中央表读取行数
          matched             命中本地用户数
          updated             发生变更并落库的用户数
          display_name_updated DisplayName 被更新的用户数
          email_updated       Email 被更新的用户数
          status_disabled     中央表停用传导到本地的用户数
          status_enabled      中央表在职恢复启用本地的用户数
          skipped_no_local    中央表有记录但本地无账号 (跳过, 不建档)
          errors              单行处理失败数
    """
    stats: Dict[str, int] = {
        "central_read": 0,
        "matched": 0,
        "updated": 0,
        "display_name_updated": 0,
        "email_updated": 0,
        "status_disabled": 0,
        "status_enabled": 0,
        "skipped_no_local": 0,
        "errors": 0,
    }

    try:
        rows = db.execute(_CENTRAL_SQL).fetchall()
    except Exception:
        logger.exception("sso_user_sync: 读取中央表 CN_AME_SSO_User 失败")
        raise

    stats["central_read"] = len(rows)
    if not rows:
        logger.info("sso_user_sync: 中央表无记录, 无需同步")
        return stats

    for login_name, display_name, email, central_status in rows:
        login_name = (login_name or "").strip()
        if not login_name:
            continue
        try:
            user = (
                db.query(User)
                .filter(User.Username == login_name, User.IsDeleted == False)  # noqa: E712
                .first()
            )
            if user is None:
                # 中央表有记录但本地无账号: 跳过, 等待首次 OIDC 登录自动建档
                stats["skipped_no_local"] += 1
                logger.info("sso_user_sync: 中央表用户 {} 本地无账号, 跳过", login_name)
                continue

            stats["matched"] += 1
            changed = False

            # 资料更新 (中央表非空才覆盖, 不用空值抹掉本地已有资料)
            if display_name and display_name != user.DisplayName:
                user.DisplayName = display_name
                stats["display_name_updated"] += 1
                changed = True
            if email and email != user.Email:
                user.Email = email
                stats["email_updated"] += 1
                changed = True

            # 状态传导 (仅命中用户; 未命中用户永不被禁用)
            central_status = int(central_status)
            if central_status == _CENTRAL_INACTIVE and user.Status == 1:
                user.Status = 0
                stats["status_disabled"] += 1
                changed = True
                logger.warning("sso_user_sync: {} 停用传导 (中央表离职/停用)", login_name)
            elif central_status == _CENTRAL_ACTIVE and user.Status == 0:
                user.Status = 1
                stats["status_enabled"] += 1
                changed = True
                logger.info("sso_user_sync: {} 恢复启用 (中央表在职)", login_name)

            if changed:
                stats["updated"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("sso_user_sync: 处理中央表用户 {} 失败, 跳过该行", login_name)

    if stats["updated"] > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("sso_user_sync: 提交失败, 本次同步变更全部回滚")
            raise

    logger.info(
        "sso_user_sync 完成: 中央 {} 人, 命中 {}, 更新 {} (姓名 {} / 邮箱 {} / "
        "停用传导 {} / 恢复 {}), 本地无账号跳过 {}, 失败 {}",
        stats["central_read"], stats["matched"], stats["updated"],
        stats["display_name_updated"], stats["email_updated"],
        stats["status_disabled"], stats["status_enabled"],
        stats["skipped_no_local"], stats["errors"],
    )
    return stats
