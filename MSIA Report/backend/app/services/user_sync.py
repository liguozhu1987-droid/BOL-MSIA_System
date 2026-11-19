"""用户同步服务

从 HR 数据库 [HRDB].[dbo].[fine_user] 同步用户到 CN_AME_MISA_User。

同步策略:
- 按 Username 比对
- 新增用户: 写入, PasswordHash 留空 (需首次登录设置或管理员重置)
- 已有用户: 更新 DisplayName / Email / Phone / Department; 不动 PasswordHash / Role
- HR 中缺失的用户: Status 置 0 (禁用)
- 每次同步写入一条 CN_AME_MISA_UserSyncLog 记录

依赖 HRDB_CONNECTION_STRING 原生 pyodbc 连接串。
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pyodbc
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.user import User, UserSyncLog
from app.utils.time import now_cst


@dataclass
class HrUser:
    """HR 用户记录"""
    username: str
    display_name: str
    email: str
    phone: str
    department: str


@dataclass
class SyncResult:
    """同步结果"""
    batch_id: str
    started_at: datetime
    finished_at: datetime
    total_read: int = 0
    total_inserted: int = 0
    total_updated: int = 0
    total_failed: int = 0
    status: str = "failed"
    error_message: str = ""
    missing_disabled: int = 0
    errors: List[str] = field(default_factory=list)


class UserSyncService:
    """用户同步服务"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn_str = settings.HRDB_CONNECTION_STRING

    def _fetch_hr_users(self) -> List[HrUser]:
        """从 HR 数据库读取用户列表

        HR 表 [HRDB].[dbo].[fine_user] 的字段:
          userName, realName, email, mobile (无 department 列)
        """
        users: List[HrUser] = []
        sql = (
            "SELECT userName, realName, email, mobile "
            "FROM [HRDB].[dbo].[fine_user] "
            "WHERE userName IS NOT NULL"
        )
        # 使用独立的 pyodbc 连接, 避免与 SQLAlchemy 主引擎混淆
        with pyodbc.connect(self.conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            for row in cursor.fetchall():
                username = (row[0] or "").strip()
                if not username:
                    continue
                users.append(
                    HrUser(
                        username=username,
                        display_name=row[1] or "",
                        email=row[2] or "",
                        phone=row[3] or "",
                        department="",  # fine_user 表无 department 列, 留空
                    )
                )
        return users

    def _fetch_single_hr_user(self, username: str) -> Optional[HrUser]:
        """从 HR 数据库读取单个用户

        Args:
            username: HR 中的用户名
        Returns:
            HrUser 或 None (未找到时)
        """
        sql = (
            "SELECT userName, realName, email, mobile "
            "FROM [HRDB].[dbo].[fine_user] "
            "WHERE userName = ?"
        )
        with pyodbc.connect(self.conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, username)
            row = cursor.fetchone()
            if row is None:
                return None
            name = (row[0] or "").strip()
            if not name:
                return None
            return HrUser(
                username=name,
                display_name=row[1] or "",
                email=row[2] or "",
                phone=row[3] or "",
                department="",  # fine_user 表无 department 列, 留空
            )

    def sync_from_hr(self, db: Session) -> SyncResult:
        """执行一次完整的 HR 用户同步

        T05-R1 #7: HR_SYNC_ENABLED=False 时直接跳过 (Status="skipped" 记入同步日志,
        不触碰任何用户数据)。SSO 派生同步 (sso_user_sync) 接管后应关闭本开关,
        防止 HRDB 缺失用户被批量禁用 (本地 ~4275 个 HR 同步用户)。

        Args:
            db: 主数据库会话
        Returns:
            SyncResult: 同步结果统计
        """
        started_at = now_cst()
        batch_id = str(uuid.uuid4())
        result = SyncResult(batch_id=batch_id, started_at=started_at, finished_at=started_at)

        if not getattr(self.settings, "HR_SYNC_ENABLED", True):
            logger.warning(
                "HR 全量同步已关闭 (hr_sync_enabled=false), 跳过批次 {} (不写任何用户数据)",
                batch_id,
            )
            result.status = "skipped"
            result.finished_at = now_cst()
            # 写入一条 skipped 日志, 便于运维确认开关生效
            try:
                db.add(UserSyncLog(
                    SyncBatchId=batch_id,
                    SyncStartedAt=started_at,
                    SyncFinishedAt=result.finished_at,
                    Status="skipped",
                    ErrorMessage="hr_sync_enabled=false, HR 全量同步已关闭",
                ))
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("写入用户同步日志失败")
            return result

        logger.info("用户同步开始, 批次 {}", batch_id)
        try:
            hr_users = self._fetch_hr_users()
            result.total_read = len(hr_users)
            logger.info("从 HR 读取到 {} 个用户", result.total_read)

            hr_usernames = {u.username for u in hr_users}

            # 已有用户索引: Username -> User
            existing = {
                u.Username: u
                for u in db.query(User).filter(User.IsDeleted == False).all()  # noqa: E712
            }

            for hr in hr_users:
                try:
                    user = existing.get(hr.username)
                    if user is None:
                        # 新增
                        # Admin 用户默认赋予管理员角色
                        default_role = "admin" if hr.username.lower() == "admin" else "reviewee"
                        new_user = User(
                            Username=hr.username,
                            DisplayName=hr.display_name or None,
                            Email=hr.email or None,
                            Phone=hr.phone or None,
                            Department=hr.department or None,
                            PasswordHash=None,  # HR 同步用户初始无密码, 首次登录用默认密码
                            Role=default_role,
                            Status=1,
                            HrSyncedAt=started_at,
                            IsDeleted=False,
                        )
                        db.add(new_user)
                        result.total_inserted += 1
                    else:
                        # 更新 (不动 PasswordHash / Role)
                        changed = False
                        if hr.display_name and hr.display_name != user.DisplayName:
                            user.DisplayName = hr.display_name
                            changed = True
                        if hr.email and hr.email != user.Email:
                            user.Email = hr.email
                            changed = True
                        if hr.phone and hr.phone != user.Phone:
                            user.Phone = hr.phone
                            changed = True
                        if hr.department and hr.department != user.Department:
                            user.Department = hr.department
                            changed = True
                        user.HrSyncedAt = started_at
                        if user.Status == 0:
                            # HR 仍存在, 恢复启用
                            user.Status = 1
                            changed = True
                        if changed:
                            result.total_updated += 1
                except Exception as exc:
                    result.total_failed += 1
                    result.errors.append(f"{hr.username}: {exc}")
                    logger.exception("同步用户 {} 失败", hr.username)

            # 禁用 HR 中缺失的用户 (仅处理同步过的用户)
            for username, user in existing.items():
                if username not in hr_usernames and user.HrSyncedAt is not None:
                    if user.Status != 0:
                        user.Status = 0
                        result.missing_disabled += 1

            db.commit()
            result.status = "success" if result.total_failed == 0 else "partial"
            logger.info(
                "用户同步完成: 新增 {} 更新 {} 失败 {} 禁用 {}",
                result.total_inserted, result.total_updated, result.total_failed,
                result.missing_disabled,
            )
        except Exception as exc:
            db.rollback()
            result.status = "failed"
            result.error_message = str(exc)[:2000]
            logger.exception("用户同步失败: {}", exc)
        finally:
            result.finished_at = now_cst()
            # 写入同步日志
            try:
                log = UserSyncLog(
                    SyncBatchId=batch_id,
                    SyncStartedAt=started_at,
                    SyncFinishedAt=result.finished_at,
                    TotalRead=result.total_read,
                    TotalInserted=result.total_inserted,
                    TotalUpdated=result.total_updated,
                    TotalFailed=result.total_failed,
                    ErrorMessage=result.error_message or ("\n".join(result.errors[:20]) or None),
                    Status=result.status,
                )
                db.add(log)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("写入用户同步日志失败")

        return result

    def sync_single_user(self, db: Session, username: str) -> SyncResult:
        """同步单个用户（用于手动触发）

        按 Username 从 HR 读取单个用户并 upsert 到本地库。
        - 新增用户: PasswordHash 留空, Role=reviewee, Status=1
        - 已有用户: 更新 DisplayName/Email/Phone/Department, 不动 PasswordHash/Role

        Args:
            db: 主数据库会话
            username: HR 中的用户名
        Returns:
            SyncResult: 同步结果统计
        """
        started_at = now_cst()
        batch_id = str(uuid.uuid4())
        result = SyncResult(batch_id=batch_id, started_at=started_at, finished_at=started_at)

        logger.info("单用户同步开始, 用户 {} 批次 {}", username, batch_id)
        try:
            hr_user = self._fetch_single_hr_user(username)
            if hr_user is None:
                result.status = "failed"
                result.error_message = f"HR 中未找到用户: {username}"
                result.errors.append(f"{username}: HR 中未找到")
                logger.warning("单用户同步: HR 中未找到用户 {}", username)
                return result

            result.total_read = 1

            existing_user = (
                db.query(User)
                .filter(User.Username == username, User.IsDeleted == False)  # noqa: E712
                .first()
            )

            if existing_user is None:
                # 新增
                new_user = User(
                    Username=hr_user.username,
                    DisplayName=hr_user.display_name or None,
                    Email=hr_user.email or None,
                    Phone=hr_user.phone or None,
                    Department=hr_user.department or None,
                    PasswordHash=None,  # HR 同步用户初始无密码
                    Role="reviewee",
                    Status=1,
                    HrSyncedAt=started_at,
                    IsDeleted=False,
                )
                db.add(new_user)
                result.total_inserted = 1
            else:
                # 更新 (不动 PasswordHash / Role)
                changed = False
                if hr_user.display_name and hr_user.display_name != existing_user.DisplayName:
                    existing_user.DisplayName = hr_user.display_name
                    changed = True
                if hr_user.email and hr_user.email != existing_user.Email:
                    existing_user.Email = hr_user.email
                    changed = True
                if hr_user.phone and hr_user.phone != existing_user.Phone:
                    existing_user.Phone = hr_user.phone
                    changed = True
                if hr_user.department and hr_user.department != existing_user.Department:
                    existing_user.Department = hr_user.department
                    changed = True
                existing_user.HrSyncedAt = started_at
                if existing_user.Status == 0:
                    # HR 仍存在, 恢复启用
                    existing_user.Status = 1
                    changed = True
                if changed:
                    result.total_updated = 1

            db.commit()
            result.status = "success"
            logger.info("单用户同步成功: {}", username)
        except Exception as exc:
            db.rollback()
            result.status = "failed"
            result.total_failed = 1
            result.error_message = str(exc)[:2000]
            result.errors.append(f"{username}: {exc}")
            logger.exception("单用户同步失败: {}", username)
        finally:
            result.finished_at = now_cst()
            # 写入同步日志
            try:
                log = UserSyncLog(
                    SyncBatchId=batch_id,
                    SyncStartedAt=started_at,
                    SyncFinishedAt=result.finished_at,
                    TotalRead=result.total_read,
                    TotalInserted=result.total_inserted,
                    TotalUpdated=result.total_updated,
                    TotalFailed=result.total_failed,
                    ErrorMessage=result.error_message or ("\n".join(result.errors[:20]) or None),
                    Status=result.status,
                )
                db.add(log)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("写入用户同步日志失败")

        return result
