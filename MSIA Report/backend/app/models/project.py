"""项目与阶段模型"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
    Unicode,
    UnicodeText,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Project(Base):
    """项目表

    Status 取值: not_started / in_progress / completed
    时间节点字段对应 MSIA 流程关键里程碑。
    """
    __tablename__ = "CN_AME_MISA_Project"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    Name = Column(Unicode(255), nullable=False)
    Code = Column(String(100), nullable=False, unique=True, index=True)
    Type = Column(Unicode(100), nullable=True)
    CmcAme = Column(Unicode(255), nullable=True)
    PlantMe = Column(Unicode(255), nullable=True)
    InalfaKickoff = Column(DateTime, nullable=True)
    SupplierKickoff = Column(DateTime, nullable=True)
    DesignFreeze = Column(DateTime, nullable=True)
    Pvp = Column(DateTime, nullable=True)
    InalfaSop = Column(DateTime, nullable=True)
    Status = Column(String(30), nullable=False, default="not_started", index=True)
    CreatedBy = Column(BigInteger, nullable=True)
    IsDeleted = Column(Boolean, nullable=False, default=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )

    phases = relationship("Phase", back_populates="project", cascade="all, delete-orphan")


class Phase(Base):
    """阶段表 - 项目下的 MSIA1..MSIA5 阶段

    Code 取值: MSIA1 / MSIA2 / MSIA3 / MSIA4 / MSIA5
    Score: 阶段总评分 (decimal 5,2)
    """
    __tablename__ = "CN_AME_MISA_Phase"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    ProjectId = Column(BigInteger, ForeignKey("CN_AME_MISA_Project.Id"), nullable=False, index=True)
    Code = Column(String(20), nullable=False, index=True)
    Name = Column(Unicode(200), nullable=True)
    TimingDescription = Column(Unicode(1000), nullable=True)
    MainTargets = Column(Unicode(2000), nullable=True)
    Status = Column(String(30), nullable=False, default="not_started", index=True)
    LeadReviewerId = Column(BigInteger, ForeignKey("CN_AME_MISA_User.Id"), nullable=True, index=True)
    Score = Column(Numeric(5, 2), nullable=True)
    CompletedAt = Column(DateTime, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )

    project = relationship("Project", back_populates="phases")
