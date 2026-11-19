"""管理后台路由

- 用户同步日志查看 / 触发同步
- 邮件日志查看 / 重发
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_role
from app.models.email_log import EmailLog
from app.models.user import User, UserSyncLog
from app.schemas.common import PageResponse
from app.services.email_service import EmailService
from app.services.user_sync import UserSyncService
from app.utils.pagination import paginate

router = APIRouter(prefix="/api/admin", tags=["管理后台"], dependencies=[Depends(require_role("admin"))])


class EmailLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    ToAddress: str
    CcAddress: Optional[str] = None
    Subject: str
    TemplateKey: Optional[str] = None
    RefType: Optional[str] = None
    RefId: Optional[int] = None
    Status: str
    ErrorMessage: Optional[str] = None
    SentAt: Optional[datetime] = None
    CreatedAt: Optional[datetime] = None


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    SyncBatchId: str
    SyncStartedAt: Optional[datetime] = None
    SyncFinishedAt: Optional[datetime] = None
    TotalRead: int
    TotalInserted: int
    TotalUpdated: int
    TotalFailed: int
    ErrorMessage: Optional[str] = None
    Status: str
    CreatedAt: Optional[datetime] = None


# ---- 用户同步 ----

@router.get("/user-sync/logs", response_model=PageResponse[SyncLogOut], summary="用户同步日志列表")
def list_sync_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(UserSyncLog).order_by(UserSyncLog.Id.desc())
    return paginate(query, page, page_size, schema=SyncLogOut)


@router.get("/user-sync/logs/{batch_id}", response_model=SyncLogOut, summary="单次同步日志详情")
def get_sync_log(batch_id: str, db: Session = Depends(get_db)):
    log = db.query(UserSyncLog).filter(UserSyncLog.SyncBatchId == batch_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="同步日志不存在")
    return log


@router.post("/user-sync/run", summary="手动触发用户同步")
def run_user_sync(db: Session = Depends(get_db)):
    """管理员手动触发一次 HR 用户同步"""
    from app.core.config import settings

    service = UserSyncService(settings)
    result = service.sync_from_hr(db)
    return {
        "message": "同步完成",
        "status": result.status,
        "batch_id": result.batch_id,
        "total_read": result.total_read,
        "total_inserted": result.total_inserted,
        "total_updated": result.total_updated,
        "total_failed": result.total_failed,
        "missing_disabled": result.missing_disabled,
    }


# ---- 邮件日志 ----

@router.get("/email/logs", response_model=PageResponse[EmailLogOut], summary="邮件日志列表")
def list_email_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(EmailLog).order_by(EmailLog.Id.desc())
    if status_filter:
        query = query.filter(EmailLog.Status == status_filter)
    return paginate(query, page, page_size, schema=EmailLogOut)


@router.post("/email/resend/{log_id}", summary="重发邮件")
def resend_email(log_id: int, db: Session = Depends(get_db)):
    """根据邮件日志重发一封邮件"""
    log = db.query(EmailLog).filter(EmailLog.Id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="邮件日志不存在")

    from app.core.config import settings

    service = EmailService(settings)
    recipients = [addr.strip() for addr in log.ToAddress.split(",") if addr.strip()]
    cc = [addr.strip() for addr in (log.CcAddress or "").split(",") if addr.strip()] or None
    ok = service.send_email(
        to=recipients,
        subject=log.Subject,
        body=log.Body or "",
        cc=cc,
        db=db,
        template_key=log.TemplateKey,
        ref_type=log.RefType,
        ref_id=log.RefId,
        skip_dedup=True,  # 管理员手动重发不受防重限制
    )
    return {"message": "重发" + ("成功" if ok else "失败"), "sent": ok}
