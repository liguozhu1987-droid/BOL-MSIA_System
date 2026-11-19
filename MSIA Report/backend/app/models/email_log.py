"""邮件日志模型 - 记录每封外发邮件

Status: queued / sent / failed
RefType / RefId: 关联业务对象 (如 issue / review), 便于追溯
"""
from sqlalchemy import BigInteger, Column, DateTime, Identity, String, Text, Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class EmailLog(Base):
    """邮件日志表"""
    __tablename__ = "CN_AME_MISA_EmailLog"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    ToAddress = Column(String(2000), nullable=False)
    CcAddress = Column(String(2000), nullable=True)
    Subject = Column(Unicode(500), nullable=False)
    Body = Column(UnicodeText, nullable=True)
    TemplateKey = Column(String(100), nullable=True, index=True)
    RefType = Column(String(50), nullable=True, index=True)
    RefId = Column(BigInteger, nullable=True, index=True)
    Status = Column(String(20), nullable=False, default="queued", index=True)
    ErrorMessage = Column(Unicode(2000), nullable=True)
    SentAt = Column(DateTime, nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
