"""用户管理路由

- 列表 / 详情 (登录即可)
- 重置密码 / 修改密码 / 修改角色 (管理员)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    PasswordResetRequest,
    PasswordUpdateRequest,
    RoleUpdateRequest,
    UserOut,
    UserOutExtended,
    UserStatusUpdateRequest,
)
from app.schemas.common import PageResponse
from app.utils.pagination import paginate
from app.utils.time import now_cst

router = APIRouter(prefix="/api/users", tags=["用户"])


@router.get("", response_model=PageResponse[UserOutExtended], summary="用户列表")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="按用户名/姓名/邮箱搜索"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """分页查询用户 (含密码状态等扩展信息)"""
    query = db.query(User).filter(User.IsDeleted == False)  # noqa: E712
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                User.Username.like(like),
                User.DisplayName.like(like),
                User.Email.like(like),
            )
        )
    query = query.order_by(User.Id)
    return paginate(query, page, page_size, schema=UserOutExtended)


@router.get("/{user_id}", response_model=UserOut, summary="用户详情")
def get_user(user_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.post(
    "/{user_id}/reset-password",
    summary="管理员重置密码",
    dependencies=[Depends(require_role("admin"))],
)
def reset_password(user_id: int, payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """管理员重置指定用户密码"""
    # P4 单轨开关: 本地密码管理关闭后, 密码生命周期归 Keycloak (方案文档 8.1)
    if not settings.LOCAL_LOGIN_ENABLED:
        raise HTTPException(
            status_code=403, detail="本地密码管理已关闭，请在统一登录页自行维护密码"
        )
    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.PasswordHash = hash_password(payload.new_password)
    user.PasswordUpdatedAt = now_cst()
    db.commit()
    return {"message": "密码已重置"}


@router.put("/{user_id}/password", summary="修改自己的密码")
def update_password(
    user_id: int,
    payload: PasswordUpdateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """用户修改自己的密码 (需校验旧密码)"""
    # P4 单轨开关: 本地密码管理关闭后, 密码生命周期归 Keycloak (方案文档 8.1)
    if not settings.LOCAL_LOGIN_ENABLED:
        raise HTTPException(
            status_code=403, detail="本地密码管理已关闭，请在统一登录页自行维护密码"
        )
    if current.Id != user_id:
        raise HTTPException(status_code=403, detail="只能修改自己的密码")
    if not verify_password(payload.old_password, current.PasswordHash or ""):
        raise HTTPException(status_code=400, detail="原密码错误")
    current.PasswordHash = hash_password(payload.new_password)
    current.PasswordUpdatedAt = now_cst()
    db.commit()
    return {"message": "密码修改成功"}


@router.put(
    "/{user_id}/role",
    summary="修改用户角色",
    dependencies=[Depends(require_role("admin"))],
)
def update_role(user_id: int, payload: RoleUpdateRequest, db: Session = Depends(get_db)):
    """管理员修改用户角色"""
    valid_roles = {"admin", "lead_reviewer", "reviewer", "reviewee"}
    if payload.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"非法角色, 可选: {valid_roles}")
    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.Role = payload.role
    db.commit()
    return {"message": "角色已更新", "role": user.Role}


@router.patch(
    "/{user_id}/status",
    summary="切换用户状态（启用/禁用）",
    dependencies=[Depends(require_role("admin"))],
)
def update_status(user_id: int, payload: UserStatusUpdateRequest, db: Session = Depends(get_db)):
    """管理员切换用户状态: 1=启用, 0=禁用"""
    if payload.Status not in (0, 1):
        raise HTTPException(status_code=400, detail="Status 仅支持 0(禁用) 或 1(启用)")
    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.Status = payload.Status
    db.commit()
    return {"message": "状态已更新", "status": user.Status}


@router.get("/{user_id}/detail", response_model=UserOutExtended, summary="用户扩展详情")
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """获取用户扩展详情（含同步信息、密码状态）"""
    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/options/all", summary="全部用户选项（下拉选择用，不分页）")
def list_user_options(
    keyword: str | None = Query(None, description="按用户名/姓名/邮箱搜索"),
    include_disabled: bool = Query(False, description="是否包含禁用用户"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回精简用户列表（Id, Username, DisplayName, Email），用于下拉选择组件。

    默认仅返回启用用户，可通过 include_disabled=true 包含禁用。
    """
    from pydantic import BaseModel

    class UserOptionOut(BaseModel):
        Id: int
        Username: str
        DisplayName: str | None
        Email: str | None
        Department: str | None

        model_config = {"from_attributes": True}

    query = db.query(User).filter(User.IsDeleted == False)  # noqa: E712
    if not include_disabled:
        query = query.filter(User.Status == 1)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                User.Username.like(like),
                User.DisplayName.like(like),
                User.Email.like(like),
                User.Department.like(like),
            )
        )
    # SQL Server 不支持 ORDER BY ... IS NULL, 用 CASE WHEN 替代
    from sqlalchemy import case
    users = query.order_by(
        case((User.DisplayName.is_(None), 1), else_=0),
        User.DisplayName,
        User.Username,
    ).all()
    return [UserOptionOut.model_validate(u) for u in users]
