"""站内通知模型

Status: unread / read
Type: 通知类型, 如 issue_assigned / issue_overdue / review_submitted
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, String, Text, Unicode, UnicodeText
from sqlalchemy.sql import func

from app.models.base import Base


class Notification(Base):
    """通知表"""
    __tablename__ = "CN_AME_MISA_Notification"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    UserId = Column(BigInteger, ForeignKey("CN_AME_MISA_User.Id"), nullable=False, index=True)
    Title = Column(Unicode(255), nullable=False)
    Content = Column(UnicodeText, nullable=True)
    Type = Column(String(50), nullable=True, index=True)
    Status = Column(String(20), nullable=False, default="unread", index=True)
    Link = Column(String(1000), nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    ReadAt = Column(DateTime, nullable=True)
