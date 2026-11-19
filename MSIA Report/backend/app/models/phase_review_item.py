"""阶段评审检查项模型 - MSIA 各阶段实际评审清单

数据来源: 00. MSIA Check list_template.xlsx 的 Report MSIA1~5 sheet
每项代表一个阶段评审时需要检查的文档/动作, 含 Request 要求 (如 Reviewed/Countersigned)
与 CheckItem (Evaluation Standards 7 档评分标准库) 分离, 互不干扰
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


class PhaseReviewItem(Base):
    """阶段评审检查项表"""
    __tablename__ = "CN_AME_MSIA_PhaseReviewItem"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # 阶段代码: MSIA1 ~ MSIA5
    PhaseCode = Column(String(20), nullable=False, index=True)
    # 关联审核标准条款 (CN_AME_MISA_CheckItem.Id, 联动来源)
    # NULL 表示来自 Excel 模板的原始条目 (无对应审核标准)
    CheckItemId = Column(BigInteger, nullable=True, index=True)
    # 序号 (1, 2, 3, ...)
    Seq = Column(Integer, nullable=False, default=1)
    # 类型: Doc. / Action
    ItemType = Column(String(20), nullable=True)
    # 检查项名称
    ItemName = Column(Unicode(500), nullable=False)
    # 要求 (如 Reviewed / Countersigned / Aligned / 空)
    Request = Column(Unicode(200), nullable=True)
    # 默认结果文本 (评审员填写)
    DefaultResultText = Column(Unicode(1000), nullable=True)
    # 排序
    SortOrder = Column(Integer, nullable=False, default=0)
    # 软删
    IsDeleted = Column(Boolean, nullable=False, default=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
