"""附件模型

OwnerType: review / issue
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, String, Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class Attachment(Base):
    """附件表"""
    __tablename__ = "CN_AME_MISA_Attachment"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    OwnerType = Column(String(30), nullable=False, index=True)
    OwnerId = Column(BigInteger, nullable=False, index=True)
    FileName = Column(Unicode(500), nullable=False)
    StoredPath = Column(String(1000), nullable=False)
    FileExtension = Column(String(20), nullable=True)
    FileSize = Column(BigInteger, nullable=True)
    MimeType = Column(String(200), nullable=True)
    UploadedBy = Column(BigInteger, ForeignKey("CN_AME_MISA_User.Id"), nullable=True, index=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
