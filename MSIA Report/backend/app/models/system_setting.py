"""系统设置模型 (键值对存储)

用于持久化管理员可配置的运行时设置, 例如:
- notification_mode: 通知模式 (test / production)
- notification_test_recipients: 测试模式下的邮件接收地址
- issue_overdue_exempt_statuses: 逾期判定豁免状态 (逗号分隔)
- issue_overdue_effective_from: Deadline 逾期规则生效时间 (北京时间)
- system_url: 系统访问地址 (邮件正文链接)

设计为通用键值表, 便于后续扩展其他运行时配置。
覆盖 config.ini 中的默认值, 修改后立即生效, 无需重启服务。

Module 字段用于按功能模块分类管理配置:
- notification: 通知模式相关
- smtp: SMTP 邮件服务器配置
- issue_closure: 问题逾期判定
- maintenance_scan: 未维护问题扫描
- escalation: 问题升级扫描
- system: 系统全局配置
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Integer,
    String,
    Unicode,
    UnicodeText,
)
from sqlalchemy.sql import func

from app.models.base import Base


class SystemSetting(Base):
    """系统设置表 (键值对)"""
    __tablename__ = "CN_AME_MISA_SystemSetting"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # 设置键 (唯一), 如 notification_mode
    SettingKey = Column(String(100), nullable=False, unique=True, index=True)
    # 设置值
    SettingValue = Column(Unicode(2000), nullable=True)
    # 显示名称 (用于前端展示)
    DisplayName = Column(Unicode(200), nullable=True)
    # 描述说明
    Description = Column(UnicodeText, nullable=True)
    # 功能模块 (用于按模块分组管理): notification/smtp/issue_closure/maintenance_scan/escalation/system
    Module = Column(String(50), nullable=True, index=True)
    # 值类型 (用于前端渲染和类型转换): string/int/float/bool
    ValueType = Column(String(20), nullable=True, default="string")
    # 排序顺序 (同一模块内的展示顺序, 越小越靠前)
    SortOrder = Column(Integer, nullable=True, default=0)
    # 最后修改人
    UpdatedBy = Column(BigInteger, nullable=True)
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
