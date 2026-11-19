"""模型汇总

在此导入所有模型类, 以便:
1. Base.metadata.create_all() 能发现全部表
2. 上层通过 `from app.models import User, Project ...` 直接引用
"""
from app.models.attachment import Attachment
from app.models.base import Base
from app.models.check_item import CheckItem
from app.models.email_log import EmailLog
from app.models.escalation_config import EscalationConfig, EscalationLog
from app.models.historic_score import HistoricScore
from app.models.issue import Issue
from app.models.issue_comment import IssueComment
from app.models.notification import Notification
from app.models.phase_review_item import PhaseReviewItem
from app.models.phase_review_meta import PhaseReviewMeta
from app.models.project import Phase, Project
from app.models.record_entry import RecordEntry
from app.models.review import ReviewRecord
from app.models.system_setting import SystemSetting
from app.models.user import User, UserSyncLog

__all__ = [
    "Base",
    "User",
    "UserSyncLog",
    "Project",
    "Phase",
    "CheckItem",
    "PhaseReviewItem",
    "PhaseReviewMeta",
    "ReviewRecord",
    "Issue",
    "IssueComment",
    "Attachment",
    "RecordEntry",
    "Notification",
    "EmailLog",
    "EscalationConfig",
    "EscalationLog",
    "HistoricScore",
    "SystemSetting",
]
