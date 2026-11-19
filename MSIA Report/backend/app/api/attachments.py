"""附件路由

- POST   /api/attachments        上传 (multipart)
- GET    /api/attachments/{id}   下载
- DELETE /api/attachments/{id}   删除
"""
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.attachment import Attachment
from app.models.issue import Issue
from app.models.review import ReviewRecord
from app.models.user import User

router = APIRouter(prefix="/api/attachments", tags=["附件"])

# 允许的属主类型
# - review: 评审记录证据
# - issue: 问题审核证据 (审核员登记问题时上传, 不可编辑)
# - issue_closure: 问题关闭证据 (被审核人申请关闭时上传, 可上传多张)
_OWNER_TYPES = {"review", "issue", "issue_closure"}
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"}
_MAX_FILE_SIZE = 10 * 1024 * 1024


def _ensure_storage() -> Path:
    storage = Path(settings.STORAGE_PATH)
    storage.mkdir(parents=True, exist_ok=True)
    return storage


def _is_issue_owner(issue: Issue, current: User) -> bool:
    return bool(
        (issue.OwnerUserId and issue.OwnerUserId == current.Id)
        or (issue.OwnerUserName and issue.OwnerUserName == current.Username)
    )


def _can_manage_issue_attachment(issue: Issue, owner_type: str, current: User) -> bool:
    if current.Role == "admin":
        return True
    if owner_type == "issue":
        return current.Role in {"lead_reviewer", "reviewer"} or _is_issue_owner(issue, current)
    return _is_issue_owner(issue, current)


def _can_manage_review_attachment(review: ReviewRecord, current: User) -> bool:
    return current.Role in {"admin", "lead_reviewer", "reviewer"} or review.ReviewerId == current.Id


def _get_attachment_owner(db: Session, record: Attachment):
    if record.OwnerType in {"issue", "issue_closure"}:
        owner = db.query(Issue).filter(Issue.Id == record.OwnerId, Issue.IsDeleted == False).first()  # noqa: E712
        if not owner:
            raise HTTPException(status_code=404, detail="问题不存在")
        return owner
    if record.OwnerType == "review":
        owner = db.query(ReviewRecord).filter(ReviewRecord.Id == record.OwnerId).first()
        if not owner:
            raise HTTPException(status_code=404, detail="审核记录不存在")
        return owner
    raise HTTPException(status_code=400, detail="附件属主类型无效")


def _can_access_attachment(record: Attachment, owner, current: User) -> bool:
    if record.OwnerType in {"issue", "issue_closure"}:
        return _can_manage_issue_attachment(owner, record.OwnerType, current)
    return _can_manage_review_attachment(owner, current)


@router.post("", summary="上传附件")
def upload_attachment(
    file: UploadFile = File(...),
    owner_type: str = "review",
    owner_id: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if owner_type not in _OWNER_TYPES:
        raise HTTPException(status_code=400, detail=f"非法 owner_type, 可选: {_OWNER_TYPES}")
    if not owner_id:
        raise HTTPException(status_code=400, detail="owner_id 不能为空")

    if owner_type == "review":
        review = db.query(ReviewRecord).filter(ReviewRecord.Id == owner_id).first()
        if not review:
            raise HTTPException(status_code=404, detail="审核记录不存在")
        if not _can_manage_review_attachment(review, current):
            raise HTTPException(status_code=403, detail="无权上传该审核记录的证据")
    elif owner_type in {"issue", "issue_closure"}:
        issue = db.query(Issue).filter(Issue.Id == owner_id, Issue.IsDeleted == False).first()  # noqa: E712
        if not issue:
            raise HTTPException(status_code=404, detail="问题不存在")
        if not _can_manage_issue_attachment(issue, owner_type, current):
            raise HTTPException(status_code=403, detail="无权上传该问题的证据")
    if file.content_type not in _IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="附件只允许上传 JPG、PNG、GIF、BMP 或 WEBP 图片")

    storage = _ensure_storage()
    # 按日期分目录
    date_dir = storage / datetime.now().strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(file.filename or "")[1].lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = date_dir / stored_name

    # 写入文件
    content = file.file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="附件大小不能超过 10 MB")
    with open(stored_path, "wb") as f:
        f.write(content)

    record = Attachment(
        OwnerType=owner_type,
        OwnerId=owner_id,
        FileName=file.filename or stored_name,
        StoredPath=str(stored_path),
        FileExtension=ext,
        FileSize=len(content),
        MimeType=file.content_type,
        UploadedBy=current.Id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.Id, "file_name": record.FileName}


@router.get("/{attachment_id}", summary="下载附件")
def download_attachment(attachment_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    record = db.query(Attachment).filter(Attachment.Id == attachment_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="附件不存在")
    owner = _get_attachment_owner(db, record)
    if not _can_access_attachment(record, owner, current):
        raise HTTPException(status_code=403, detail="无权访问该附件")
    path = Path(record.StoredPath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(
        path=str(path),
        filename=record.FileName,
        media_type=record.MimeType or "application/octet-stream",
    )


@router.delete("/{attachment_id}", summary="删除附件")
def delete_attachment(attachment_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    record = db.query(Attachment).filter(Attachment.Id == attachment_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="附件不存在")
    owner = _get_attachment_owner(db, record)
    if not _can_access_attachment(record, owner, current):
        raise HTTPException(status_code=403, detail="无权删除该附件")
    # 尝试删除物理文件
    try:
        path = Path(record.StoredPath)
        if path.exists():
            path.unlink()
    except OSError:
        pass
    db.delete(record)
    db.commit()
    return {"message": "附件已删除"}
