"""阶段路由"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.project import Phase, Project
from app.models.user import User
from app.schemas.phase import PhaseConfirmRequest, PhaseOut, PhaseUpdate
from app.utils.time import now_cst

router = APIRouter(prefix="/api", tags=["阶段"])


@router.get("/projects/{project_id}/phases", summary="项目下所有阶段")
def list_project_phases(
    project_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[PhaseOut]:
    phases = (
        db.query(Phase)
        .filter(Phase.ProjectId == project_id)
        .order_by(Phase.Code)
        .all()
    )
    return [PhaseOut.model_validate(p, from_attributes=True) for p in phases]


@router.get("/phases/{phase_id}", response_model=PhaseOut, summary="阶段详情")
def get_phase(phase_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    phase = db.query(Phase).filter(Phase.Id == phase_id).first()
    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")
    return phase


@router.put(
    "/phases/{phase_id}",
    response_model=PhaseOut,
    summary="更新阶段",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def update_phase(phase_id: int, payload: PhaseUpdate, db: Session = Depends(get_db)):
    phase = db.query(Phase).filter(Phase.Id == phase_id).first()
    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(phase, k, v)
    db.commit()
    db.refresh(phase)
    return phase


@router.post(
    "/phases/{phase_id}/confirm",
    response_model=PhaseOut,
    summary="确认阶段 (lead_reviewer)",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def confirm_phase(
    phase_id: int,
    payload: PhaseConfirmRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """确认阶段完成, 记录评分与完成时间"""
    phase = db.query(Phase).filter(Phase.Id == phase_id).first()
    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")
    if payload.Score is not None:
        phase.Score = payload.Score
    phase.Status = "completed"
    phase.CompletedAt = now_cst()
    db.commit()
    db.refresh(phase)
    return phase
