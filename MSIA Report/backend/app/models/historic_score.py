"""历史评分录入模型

用于将系统上线前已经审核完成的项目评分值直接录入系统。
每个 MSIA 计划 (planId) 的每个阶段 (MSIA1~5) 可录入一条历史评分。

与正常评审流程 (ReviewRecord) 分离:
- 正常流程: 逐条评价检查项后计算平均分
- 历史录入: 项目已在系统外审核完成, 直接录入阶段总分
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    Unicode,
    UnicodeText,
)
from sqlalchemy.sql import func

from app.models.base import Base


class HistoricScore(Base):
    """历史评分录入表 (项目阶段总分)"""
    __tablename__ = "CN_AME_MISA_HistoricScore"
    __table_args__ = (
        # 每个项目每个阶段仅一条历史评分
        UniqueConstraint("PlanId", "PhaseCode", name="UX_MISA_HistoricScore_PlanId_PhaseCode"),
    )

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # MSIA 计划 ID (HRDB 主键, 字符串)
    PlanId = Column(String(100), nullable=False, index=True)
    # 工单 ID (冗余, 便于检索)
    OrderId = Column(String(100), nullable=True, index=True)
    # 项目名称 (冗余, 便于展示)
    ProjectName = Column(Unicode(500), nullable=True)
    # 阶段代码: MSIA1 ~ MSIA5
    PhaseCode = Column(String(20), nullable=False, index=True)
    # 阶段评分 (0-1 小数, 与 ReviewRecord.Score 格式一致; 如 0.78 = 78%)
    Score = Column(Numeric(5, 2), nullable=False)
    # 备注
    Remark = Column(UnicodeText, nullable=True)
    CreatedBy = Column(BigInteger, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
