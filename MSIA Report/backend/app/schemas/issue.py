"""问题数据模型"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

IssueStatus = Literal["open", "in_progress", "pending_verification", "closed"]
IssuePriority = Literal["high", "medium", "low"]
IssueSeverity = Literal["H", "M", "L"]


class IssueBase(BaseModel):
    # ProjectId 可空 (MSIA 计划项目通过 PlanId 关联)
    ProjectId: Optional[int] = None
    PhaseId: Optional[int] = None
    ItemId: Optional[int] = None
    # 阶段评审检查项 ID
    PhaseReviewItemId: Optional[int] = None
    # MSIA 计划 ID (字符串, 来自 HRDB)
    PlanId: Optional[str] = Field(None, max_length=100)
    # 阶段代码 (MSIA1~MSIA5)
    PhaseCode: Optional[str] = Field(None, max_length=20)
    # 检查项编号 (冗余, 便于汇总)
    ItemNo: Optional[str] = Field(None, max_length=50)
    IssueNo: Optional[str] = Field(None, max_length=100, description="留空则系统自动生成")
    Title: str = Field(..., max_length=500)
    Description: Optional[str] = None
    OwnerUserId: Optional[int] = None
    # 责任人英文账号 (来自 HRDB userName_in_charge, 用于权限匹配)
    OwnerUserName: Optional[str] = Field(None, max_length=100)
    # 责任人姓名 (默认为项目负责人)
    OwnerName: Optional[str] = Field(None, max_length=100)
    # 责任人所属公司
    OwnerCompany: Optional[str] = Field(None, max_length=200)
    OwnerDepartment: Optional[str] = None
    # 优先级: high/medium/low
    Priority: IssuePriority = Field("medium", description="high/medium/low")
    # 严重等级: H / M / L
    Severity: IssueSeverity = Field("M", description="H/M/L")
    DueDate: Optional[datetime] = None
    Status: IssueStatus = Field("open", description="open/in_progress/pending_verification/closed")
    Remarks: Optional[str] = None


class IssueCreate(IssueBase):
    pass


class IssueUpdate(BaseModel):
    Title: Optional[str] = None
    Description: Optional[str] = None
    OwnerUserId: Optional[int] = None
    OwnerUserName: Optional[str] = None
    OwnerName: Optional[str] = None
    OwnerCompany: Optional[str] = None
    OwnerDepartment: Optional[str] = None
    Priority: Optional[IssuePriority] = None
    Severity: Optional[IssueSeverity] = None
    DueDate: Optional[datetime] = None
    Status: Optional[IssueStatus] = None
    Remarks: Optional[str] = None
    # 整改完成日期 (Deadline): 人工修改; 留空时系统按阶段实际审核日期+10天自动填充
    Deadline: Optional[datetime] = None
    # 工作台扩展字段
    RootCause: Optional[str] = None
    CorrectiveAction: Optional[str] = None
    PlannedCloseDate: Optional[datetime] = None


class IssueStatusUpdate(BaseModel):
    """问题状态变更 + 验证意见"""
    Status: IssueStatus = Field(..., description="open/in_progress/pending_verification/closed")
    ClosingStatus: Optional[str] = None
    VerificationComments: Optional[str] = None


class IssueWorkbenchUpdate(BaseModel):
    """工作台问题更新: 被审核人维护原因、措施、计划日期"""
    RootCause: Optional[str] = None
    CorrectiveAction: Optional[str] = None
    PlannedCloseDate: Optional[datetime] = None
    OwnerName: Optional[str] = None
    OwnerCompany: Optional[str] = None
    OwnerDepartment: Optional[str] = None


class IssueClosureRequest(BaseModel):
    """被审核人申请关闭问题"""
    VerificationComments: Optional[str] = None


class IssueClosureApproval(BaseModel):
    """管理员/主审核员审批关闭申请"""
    Approved: bool = Field(..., description="True=批准关闭, False=驳回")
    VerificationComments: Optional[str] = None


class IssueReopen(BaseModel):
    """重开已关闭问题 (清零评分管控字段, 重新走整改闭环)"""
    Reason: str = Field(..., min_length=1, max_length=2000, description="重开原因 (必填, 记入评论历史)")


class AttachmentOut(BaseModel):
    """附件输出 (审核证据)"""
    model_config = ConfigDict(from_attributes=True)

    Id: int
    OwnerType: str
    OwnerId: int
    FileName: str
    FileExtension: Optional[str] = None
    FileSize: Optional[int] = None
    MimeType: Optional[str] = None
    UploadedBy: Optional[int] = None
    CreatedAt: Optional[datetime] = None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    ProjectId: Optional[int] = None
    PhaseId: Optional[int] = None
    ItemId: Optional[int] = None
    PhaseReviewItemId: Optional[int] = None
    PlanId: Optional[str] = None
    PhaseCode: Optional[str] = None
    ItemNo: Optional[str] = None
    # 项目名称 (非数据库字段, 由 API 从 HRDB 注入; 无关联项目时为空字符串)
    ProjectName: str = ""
    # 检查项名称 (非数据库字段, 由 API 注入, 便于定位评分条款)
    ItemName: str = ""
    IssueNo: str
    Title: str
    Description: Optional[str] = None
    OwnerUserId: Optional[int] = None
    OwnerUserName: Optional[str] = None
    OwnerName: Optional[str] = None
    OwnerCompany: Optional[str] = None
    OwnerDepartment: Optional[str] = None
    Priority: str
    Severity: str
    DueDate: Optional[datetime] = None
    Status: str
    ClosingStatus: Optional[str] = None
    VerificationComments: Optional[str] = None
    VerifiedBy: Optional[int] = None
    VerifiedAt: Optional[datetime] = None
    ClosedAt: Optional[datetime] = None
    # 工作台扩展字段
    RootCause: Optional[str] = None
    CorrectiveAction: Optional[str] = None
    PlannedCloseDate: Optional[datetime] = None
    # 整改完成日期 (逾期判定硬边界; 阶段实际审核日期+10自然日, 可人工调整)
    Deadline: Optional[datetime] = None
    DeadlineIsManual: bool = False
    ClosureRequestedAt: Optional[datetime] = None
    ClosureRequestedBy: Optional[int] = None
    # ===== 评分管控 =====
    # 整改前评分 (批准关闭时快照)
    ScoreAtClosure: Optional[float] = None
    # 整改后评分 (关闭后重新评分回写; 已关闭且为空 = 待更新评分)
    ScoreAfterUpdate: Optional[float] = None
    # 整改后评分更新时间
    ScoreUpdatedAt: Optional[datetime] = None
    Remarks: Optional[str] = None
    CreatedBy: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None
    # 审核证据附件列表 (非数据库字段, 由 API 注入)
    Evidence: list[AttachmentOut] = Field(default_factory=list, description="审核证据附件 (审核员登记时上传)")
    # 关闭证据附件列表 (非数据库字段, 由 API 注入)
    ClosureEvidence: list[AttachmentOut] = Field(default_factory=list, description="关闭证据附件 (被审核人申请关闭时上传)")


class IssueStatsOut(BaseModel):
    """问题统计"""
    total: int = 0
    open_count: int = 0
    in_progress_count: int = 0
    pending_verification_count: int = 0
    closed_count: int = 0
    overdue_count: int = 0
    high_priority_count: int = 0


class IssueCommentCreate(BaseModel):
    """问题评论创建"""
    Content: str = Field(..., min_length=1, max_length=4000)
    Action: str = Field(
        "comment",
        description="comment|status_change|verify|assign",
    )


class IssueCommentOut(BaseModel):
    """问题评论输出"""
    model_config = ConfigDict(from_attributes=True)

    Id: int
    IssueId: int
    AuthorUserId: Optional[int] = None
    AuthorName: Optional[str] = None
    Action: str
    Content: str
    FromStatus: Optional[str] = None
    ToStatus: Optional[str] = None
    CreatedAt: Optional[datetime] = None
