"""问题跟踪模型

Status 取值: open / in_progress / pending_verification / closed
Priority 取值: high / medium / low
"""
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
from sqlalchemy.sql import func

from app.models.base import Base


class Issue(Base):
    """问题表"""
    __tablename__ = "CN_AME_MISA_Issue"

    Id = Column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    # ProjectId 可空 (MSIA 计划项目不一定在 Project 表中, 通过 PlanId 关联)
    ProjectId = Column(BigInteger, ForeignKey("CN_AME_MISA_Project.Id"), nullable=True, index=True)
    PhaseId = Column(BigInteger, ForeignKey("CN_AME_MISA_Phase.Id"), nullable=True, index=True)
    ItemId = Column(BigInteger, ForeignKey("CN_AME_MISA_CheckItem.Id"), nullable=True, index=True)
    # 阶段评审检查项 ID (关联 PhaseReviewItem)
    PhaseReviewItemId = Column(BigInteger, ForeignKey("CN_AME_MSIA_PhaseReviewItem.Id"), nullable=True, index=True)
    # MSIA 计划 ID (来自 HRDB, 字符串类型, 便于关联项目实际数据)
    PlanId = Column(String(100), nullable=True, index=True)
    # 阶段代码 (MSIA1~MSIA5, 冗余字段便于查询)
    PhaseCode = Column(String(20), nullable=True, index=True)
    # 检查项编号 (冗余, 便于汇总问题时建立关联)
    ItemNo = Column(String(50), nullable=True, index=True)
    IssueNo = Column(String(100), nullable=False, unique=True, index=True)
    Title = Column(Unicode(500), nullable=False)
    # 使用 UnicodeText (NVARCHAR MAX) 支持中文等 Unicode 字符
    Description = Column(UnicodeText, nullable=True)
    OwnerUserId = Column(BigInteger, ForeignKey("CN_AME_MISA_User.Id"), nullable=True, index=True)
    # 责任人英文账号 (来自 HRDB userName_in_charge, 用于与登录用户 Username 匹配)
    OwnerUserName = Column(String(100), nullable=True, index=True)
    # 责任人姓名 (默认为项目负责人)
    OwnerName = Column(Unicode(100), nullable=True)
    # 责任人所属公司
    OwnerCompany = Column(Unicode(200), nullable=True)
    OwnerDepartment = Column(Unicode(200), nullable=True)
    # 优先级: high(H) / medium(M) / low(L)
    Priority = Column(String(20), nullable=False, default="medium", index=True)
    # 严重等级: H / M / L
    Severity = Column(String(2), nullable=False, default="M", index=True)
    DueDate = Column(DateTime, nullable=True, index=True)
    Status = Column(String(30), nullable=False, default="open", index=True)
    ClosingStatus = Column(Unicode(200), nullable=True)
    VerificationComments = Column(UnicodeText, nullable=True)
    VerifiedBy = Column(BigInteger, nullable=True)
    VerifiedAt = Column(DateTime, nullable=True)
    ClosedAt = Column(DateTime, nullable=True)
    # 工作台扩展: 原因分析、纠正措施、计划完成日期
    RootCause = Column(UnicodeText, nullable=True)
    CorrectiveAction = Column(UnicodeText, nullable=True)
    PlannedCloseDate = Column(DateTime, nullable=True, index=True)
    # 关闭申请: 被审核人提交关闭申请后, 状态变为 pending_verification
    ClosureRequestedAt = Column(DateTime, nullable=True)
    ClosureRequestedBy = Column(BigInteger, nullable=True)
    # ===== 整改完成日期 (Deadline) =====
    # Deadline: 整改完成期限 = 阶段实际审核完成日期 (HRDB msia_plan) + 10 自然日
    #   MSIA1/2/3 → msia3ActualDate, MSIA4 → msia4ActualDate, MSIA5 → msia5ActualDate
    #   作为问题逾期判定的唯一硬边界; 为空 (阶段评审未完成) 的问题不参与逾期判定
    Deadline = Column(DateTime, nullable=True, index=True)
    # DeadlineIsManual: 是否被人工修改 (人工修改后自动回填不再覆盖)
    DeadlineIsManual = Column(Boolean, nullable=False, default=False)
    # ===== 评分管控 (问题关闭 → 审核条款评分更新闭环) =====
    # 整改前评分: 问题批准关闭时, 快照该检查项当时的最新评分
    ScoreAtClosure = Column(Numeric(5, 2), nullable=True)
    # 整改后评分: 问题关闭后审核员重新评分时自动回写 (为空表示待更新评分)
    ScoreAfterUpdate = Column(Numeric(5, 2), nullable=True)
    # 整改后评分的更新时间
    ScoreUpdatedAt = Column(DateTime, nullable=True)
    Remarks = Column(UnicodeText, nullable=True)
    CreatedBy = Column(BigInteger, nullable=True)
    IsDeleted = Column(Boolean, nullable=False, default=False)
    CreatedAt = Column(DateTime, nullable=False, server_default=func.sysdatetime())
    UpdatedAt = Column(
        DateTime,
        nullable=False,
        server_default=func.sysdatetime(),
        onupdate=func.sysdatetime(),
    )
