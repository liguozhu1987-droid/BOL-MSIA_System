"""通知路由"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.common import PageResponse
from app.utils.pagination import paginate
from app.utils.time import now_cst


class NotificationOut(BaseModel):
    """通知输出"""
    model_config = ConfigDict(from_attributes=True)

    Id: int
    UserId: int
    Title: str
    Content: Optional[str] = None
    Type: Optional[str] = None
    Status: str
    Link: Optional[str] = None
    CreatedAt: Optional[datetime] = None
    ReadAt: Optional[datetime] = None


router = APIRouter(prefix="/api/notifications", tags=["通知"])


@router.get("", response_model=PageResponse[NotificationOut], summary="我的通知列表")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.UserId == current.Id)
    if status_filter:
        query = query.filter(Notification.Status == status_filter)
    query = query.order_by(Notification.Id.desc())
    return paginate(query, page, page_size, schema=NotificationOut)


@router.patch("/{notification_id}", summary="标记单条通知为已读")
def mark_read(notification_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    notif = (
        db.query(Notification)
        .filter(Notification.Id == notification_id, Notification.UserId == current.Id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="通知不存在")
    notif.Status = "read"
    notif.ReadAt = now_cst()
    db.commit()
    return {"message": "已标记为已读"}


@router.post("/mark-read", summary="标记全部未读通知为已读")
def mark_all_read(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    updated = (
        db.query(Notification)
        .filter(Notification.UserId == current.Id, Notification.Status == "unread")
        .update({Notification.Status: "read", Notification.ReadAt: now_cst()})
    )
    db.commit()
    return {"message": "已全部标记为已读", "updated": updated}
