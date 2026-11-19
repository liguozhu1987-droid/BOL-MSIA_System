"""问题升级配置模型

按 工厂(Plant) + 严重等级(Severity: H/M/L) 二维配置升级规则。

升级流程 (SLA 时间阈值触发):
- Level 1: 问题登记后 N 小时未响应 (未维护原因/措施) → 发送给责任人
- Level 2: 超过 Level1 仍无响应 → 升级给部门经理 (Level2Recipients)
- Level 3: 超过 Level2 仍无响应 → 升级给 AME Director (Level3Recipients)

每小时由调度器扫描一次, 依据配置触发对应级别的邮件。
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
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


class EscalationConfig(Base):
    """升级配置表 (工厂 × 严重等级)"""
    __tablename__ = "CN_AME_MISA_EscalationConfig"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # 工厂名称 (如 广州 / 北京 / 上海), 与 HRDB location 对应
    Plant = Column(Unicode(100), nullable=False, index=True)
    # 严重等级: H / M / L
    Severity = Column(String(2), nullable=False, index=True)
    # Level1 触发小时数 (问题登记后多少小时未响应触发 Level1)
    Level1Hours = Column(Integer, nullable=False, default=4)
    # Level2 触发小时数 (相对 Level1 的小时数)
    Level2Hours = Column(Integer, nullable=False, default=8)
    # Level3 触发小时数 (相对 Level1 的小时数)
    Level3Hours = Column(Integer, nullable=False, default=24)
    # Level1 收件人 (留空则使用责任人邮箱)
    Level1Recipients = Column(Unicode(1000), nullable=True)
    # Level2 收件人 (部门经理邮箱, 分号分隔)
    Level2Recipients = Column(Unicode(1000), nullable=True)
    # Level3 收件人 (AME Director 邮箱, 分号分隔)
    Level3Recipients = Column(Unicode(1000), nullable=True)
    # 是否启用
    IsEnabled = Column(Boolean, nullable=False, default=True, index=True)
    # 备注
    Remarks = Column(UnicodeText, nullable=True)
    CreatedBy = Column(BigInteger, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )


class EscalationLog(Base):
    """升级日志表 - 记录每次升级邮件发送"""
    __tablename__ = "CN_AME_MISA_EscalationLog"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    IssueId = Column(BigInteger, nullable=False, index=True)
    ConfigId = Column(BigInteger, nullable=True, index=True)
    # 升级级别: 1 / 2 / 3
    Level = Column(Integer, nullable=False, index=True)
    # 第 N 次提醒 (同级别重复发送计数)
    RemindCount = Column(Integer, nullable=True, default=1)
    # 实际发送邮箱 (分号分隔; 测试模式下为重定向后的测试邮箱)
    Recipients = Column(Unicode(1000), nullable=False)
    # 原始收件人 (测试模式重定向前; 生产模式下与 Recipients 相同)
    OriginalRecipients = Column(Unicode(1000), nullable=True)
    # 关联的 EmailLog.Id
    EmailLogId = Column(BigInteger, nullable=True)
    SentAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
