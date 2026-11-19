"""项目路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.project import Project
from app.models.user import User
from app.schemas.common import PageResponse
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.utils.pagination import paginate

router = APIRouter(prefix="/api/projects", tags=["项目"])


@router.get("", response_model=PageResponse[ProjectOut], summary="项目列表")
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(Project).filter(Project.IsDeleted == False)  # noqa: E712
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(Project.Name.like(like), Project.Code.like(like)))
    if status_filter:
        query = query.filter(Project.Status == status_filter)
    query = query.order_by(Project.Id.desc())
    return paginate(query, page, page_size, schema=ProjectOut)


@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建项目",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    exists = db.query(Project).filter(Project.Code == payload.Code).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"项目代码已存在: {payload.Code}")
    project = Project(**payload.model_dump(), CreatedBy=current.Id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut, summary="项目详情")
def get_project(project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.Id == project_id, Project.IsDeleted == False).first()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.put(
    "/{project_id}",
    response_model=ProjectOut,
    summary="更新项目",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.Id == project_id, Project.IsDeleted == False).first()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = payload.model_dump(exclude_unset=True)
    if "Code" in data and data["Code"] != project.Code:
        dup = db.query(Project).filter(Project.Code == data["Code"]).first()
        if dup:
            raise HTTPException(status_code=400, detail="项目代码已存在")
    for k, v in data.items():
        setattr(project, k, v)
    db.commit()
    db.refresh(project)
    return project


@router.delete(
    "/{project_id}",
    summary="删除项目 (软删)",
    dependencies=[Depends(require_role("admin"))],
)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.Id == project_id, Project.IsDeleted == False).first()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.IsDeleted = True
    db.commit()
    return {"message": "项目已删除"}
