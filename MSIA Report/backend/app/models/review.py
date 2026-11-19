"""审核记录模型 - 每个检查项的评审结果

Status 取值: draft / submitted / confirmed
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
)
from sqlalchemy import Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class ReviewRecord(Base):
    """审核记录表"""
    __tablename__ = "CN_AME_MISA_ReviewRecord"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # 旧外键字段 (历史遗留, 已改为可空, 实际关联通过 PhaseReviewItemId + PlanId)
    ProjectId = Column(BigInteger, nullable=True, index=True)
    PhaseId = Column(BigInteger, nullable=True, index=True)
    ItemId = Column(BigInteger, nullable=True, index=True)
    # 阶段评审检查项 ID (关联 PhaseReviewItem, 可空, 兼容旧审核记录)
    PhaseReviewItemId = Column(BigInteger, ForeignKey("CN_AME_MSIA_PhaseReviewItem.Id"), nullable=True, index=True)
    # 阶段代码 (MSIA1~MSIA5, 冗余字段便于查询)
    PhaseCode = Column(String(20), nullable=True, index=True)
    # 检查项编号 (冗余, 便于汇总)
    ItemNo = Column(String(50), nullable=True, index=True)
    # MSIA 计划 ID (来自 HRDB, 字符串类型, 关联具体项目的评审记录)
    PlanId = Column(String(100), nullable=True, index=True)
    ReviewerId = Column(BigInteger, ForeignKey("CN_AME_MISA_User.Id"), nullable=False, index=True)
    Score = Column(Numeric(5, 2), nullable=True)
    ResultText = Column(Unicode(1000), nullable=True)
    # 使用 UnicodeText (NVARCHAR MAX) 支持中文等 Unicode 字符
    Comments = Column(UnicodeText, nullable=True)
    Status = Column(String(20), nullable=False, default="draft", index=True)
    SubmittedAt = Column(DateTime, nullable=True)
    ConfirmedAt = Column(DateTime, nullable=True)
    ConfirmedBy = Column(BigInteger, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
