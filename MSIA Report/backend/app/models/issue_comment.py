"""问题评论模型 - 简单的问题跟踪历史记录

用于记录问题的处理过程、整改说明、验证意见等对话式跟踪。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    Unicode,
    UnicodeText,
)
from sqlalchemy.sql import func

from app.models.base import Base


class IssueComment(Base):
    """问题评论表 (简单问题跟踪历史)"""
    __tablename__ = "CN_AME_MISA_IssueComment"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    IssueId = Column(
        BigInteger,
        ForeignKey("CN_AME_MISA_Issue.Id"),
        nullable=False,
        index=True,
    )
    AuthorUserId = Column(
        BigInteger,
        ForeignKey("CN_AME_MISA_User.Id"),
        nullable=True,
        index=True,
    )
    AuthorName = Column(Unicode(200), nullable=True)
    Action = Column(String(50), nullable=False, default="comment")
    Content = Column(UnicodeText, nullable=False)
    FromStatus = Column(String(30), nullable=True)
    ToStatus = Column(String(30), nullable=True)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
