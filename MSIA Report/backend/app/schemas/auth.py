"""认证相关数据模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class UserOut(BaseModel):
    """用户对外输出"""
    model_config = ConfigDict(from_attributes=True)

    Id: int
    Username: str
    DisplayName: Optional[str] = None
    Email: Optional[str] = None
    Phone: Optional[str] = None
    Department: Optional[str] = None
    Role: str
    Status: int


class UserStatusUpdateRequest(BaseModel):
    """用户状态切换"""
    Status: int  # 1=启用, 0=禁用


class UserOutExtended(UserOut):
    """用户扩展信息（含同步信息和密码状态）"""
    HrSyncedAt: Optional[datetime] = None
    PasswordUpdatedAt: Optional[datetime] = None
    IsDeleted: bool = False
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None
    HasPassword: bool = False  # 是否已设置密码


class TokenResponse(BaseModel):
    """登录成功返回的令牌"""
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class OtkExchangeRequest(BaseModel):
    """OIDC 一次性码 (otk) 换本地 JWT 的请求

    OIDC 回调成功后后端签发 60s 有效的一次性码, 前端凭此换登录态,
    避免本地 JWT 出现在 URL 跳转链中。
    """
    otk: str


class PasswordUpdateRequest(BaseModel):
    """修改密码"""
    old_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    """管理员重置密码"""
    new_password: str


class RoleUpdateRequest(BaseModel):
    """修改角色"""
    role: str  # admin / lead_reviewer / reviewer / reviewee
