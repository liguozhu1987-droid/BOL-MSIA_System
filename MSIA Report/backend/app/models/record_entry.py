"""记录条目模型 - 用于导出审核记录表

每条对应一个检查项的最终记录结果。
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, String, Text, Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class RecordEntry(Base):
    """记录条目表"""
    __tablename__ = "CN_AME_MISA_RecordEntry"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    ProjectId = Column(BigInteger, ForeignKey("CN_AME_MISA_Project.Id"), nullable=False, index=True)
    PhaseId = Column(BigInteger, ForeignKey("CN_AME_MISA_Phase.Id"), nullable=True, index=True)
    ItemId = Column(BigInteger, ForeignKey("CN_AME_MISA_CheckItem.Id"), nullable=True, index=True)
    MsiaCode = Column(String(20), nullable=True, index=True)
    ItemName = Column(Unicode(500), nullable=True)
    Request = Column(Unicode(2000), nullable=True)
    Result = Column(Unicode(1000), nullable=True)
    Comments = Column(UnicodeText, nullable=True)
    IssueDueDate = Column(DateTime, nullable=True)
    IssueStatus = Column(String(30), nullable=True)
    Remarks = Column(UnicodeText, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
