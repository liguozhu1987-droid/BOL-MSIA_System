"""阶段评审元数据模型 - 每个项目每个 MSIA 阶段的报告附加信息

用于审核报告 (Report MSIA1~5) 中需要人工维护的字段:
- ReviewPlace: 评审地点 (一般为 Teams 会议)
- CmcAme: CMC AME (默认为空, 由审核员手动维护)
- InalfaKickoff / SupplierKickoff / DesignFreeze / Pvp / InalfaSop:
  报告 Milestones 面板的 5 个项目里程碑时间点 (HRDB 无此数据, 手动维护)

按 (PlanId, PhaseCode) 唯一, 在项目管理界面中由审核员手动维护;
CMC AME 与里程碑为项目级数据, 保存时同步到同项目所有阶段。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    String,
    Text,
    Unicode,
    UniqueConstraint,
)

from sqlalchemy.sql import func

from app.models.base import Base


class PhaseReviewMeta(Base):
    """阶段评审元数据表 (审核报告附加信息)"""
    __tablename__ = "CN_AME_MISA_PhaseReviewMeta"
    __table_args__ = (
        UniqueConstraint("PlanId", "PhaseCode", name="UQ_PhaseReviewMeta_Plan_Phase"),
    )

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # MSIA 计划 ID (HRDB msia_plan.ID, 字符串)
    PlanId = Column(String(100), nullable=False, index=True)
    # 阶段代码: MSIA1 ~ MSIA5
    PhaseCode = Column(String(20), nullable=False, index=True)
    # 评审地点 (如 Teams / 现场会议地点)
    ReviewPlace = Column(Unicode(500), nullable=True)
    # CMC AME (覆盖 HRDB leadUser 默认值, 项目级)
    CmcAme = Column(Unicode(255), nullable=True)
    # 报告 Milestones 面板的 5 个项目里程碑时间点 (项目级, 手动维护)
    InalfaKickoff = Column(Unicode(50), nullable=True)
    SupplierKickoff = Column(Unicode(50), nullable=True)
    DesignFreeze = Column(Unicode(50), nullable=True)
    Pvp = Column(Unicode(50), nullable=True)
    InalfaSop = Column(Unicode(50), nullable=True)
    # 维护人 / 时间
    UpdatedBy = Column(BigInteger, nullable=True)
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
