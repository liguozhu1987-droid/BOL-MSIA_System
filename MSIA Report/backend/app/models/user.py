"""用户与用户同步日志模型"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Identity, SmallInteger, String, Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class User(Base):
    """用户表 - 系统登录与权限主体

    Role 取值: admin / lead_reviewer / reviewer / reviewee
    Status: 1 启用 / 0 禁用

    中文相关字段使用 Unicode (NVARCHAR) 类型, 避免中文乱码 (????)
    """
    __tablename__ = "CN_AME_MISA_User"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    Username = Column(String(100), nullable=False, unique=True, index=True)
    # DisplayName 可能包含中文, 使用 Unicode (NVARCHAR) 避免乱码
    DisplayName = Column(Unicode(200), nullable=True)
    # RealName 提取自 DisplayName 括号内中文 (如 "LF01047(路玉龙)Yulong Lu" -> "路玉龙")
    RealName = Column(Unicode(100), nullable=True, index=True)
    Email = Column(String(255), nullable=True, index=True)
    Phone = Column(String(50), nullable=True)
    # Department 含中文, 使用 Unicode
    Department = Column(Unicode(200), nullable=True)
    PasswordHash = Column(String(255), nullable=True)
    PasswordUpdatedAt = Column(DateTime, nullable=True)
    Role = Column(String(50), nullable=False, default="reviewee", index=True)
    Status = Column(SmallInteger, nullable=False, default=1, index=True)
    HrSyncedAt = Column(DateTime, nullable=True)
    IsDeleted = Column(Boolean, nullable=False, default=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )

    @property
    def HasPassword(self) -> bool:
        """是否已设置密码 (PasswordHash 非空)"""
        return bool(self.PasswordHash)


class UserSyncLog(Base):
    """用户同步日志 - 记录每次 HR 数据同步结果

    Status 取值: success / partial / failed
    """
    __tablename__ = "CN_AME_MISA_UserSyncLog"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    SyncBatchId = Column(String(64), nullable=False, unique=True, index=True)
    SyncStartedAt = Column(DateTime, nullable=False)
    SyncFinishedAt = Column(DateTime, nullable=True)
    TotalRead = Column(BigInteger, nullable=False, default=0)
    TotalInserted = Column(BigInteger, nullable=False, default=0)
    TotalUpdated = Column(BigInteger, nullable=False, default=0)
    TotalFailed = Column(BigInteger, nullable=False, default=0)
    ErrorMessage = Column(Unicode(2000), nullable=True)
    Status = Column(String(20), nullable=False, default="failed", index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
