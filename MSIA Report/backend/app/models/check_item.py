"""检查项模型 - MSIA 评审检查项定义

ScoreScaleType: 7-step (默认, 对应 Excel Maturity 7 档: 0/25/33/50/67/75/100)
ScoreOptions: JSON 文本, 存储 7 档 Maturity 评分描述
ReviewerRoles: 逗号分隔的角色串, 如 "lead_reviewer,reviewer"
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Identity,
    Integer,
    String,
    Text,
    Unicode,
    UnicodeText,
)
from sqlalchemy.sql import func

from app.models.base import Base


class CheckItem(Base):
    """检查项表"""
    __tablename__ = "CN_AME_MISA_CheckItem"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    PhaseCode = Column(String(20), nullable=False, index=True)
    ItemNo = Column(String(50), nullable=False)
    Name = Column(Unicode(500), nullable=False)
    Request = Column(Unicode(2000), nullable=True)
    RequestDescription = Column(UnicodeText, nullable=True)
    IsKeyItem = Column(Boolean, nullable=False, default=False)
    ReviewerRoles = Column(String(500), nullable=True)
    ReferenceDocuments = Column(UnicodeText, nullable=True)
    ScoreScaleType = Column(String(20), nullable=False, default="7-step")
    ScoreOptions = Column(UnicodeText, nullable=True)  # JSON 文本
    DefaultResultText = Column(Unicode(1000), nullable=True)
    Version = Column(Integer, nullable=False, default=1)
    Remarks = Column(UnicodeText, nullable=True)
    # 审核条款启用/停用开关 (默认启用); 停用后不进入项目评审打分场景
    IsActive = Column(Boolean, nullable=False, default=True)
    IsDeleted = Column(Boolean, nullable=False, default=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
