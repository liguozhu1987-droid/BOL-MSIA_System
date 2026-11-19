"""FastAPI 依赖

- get_db: 数据库会话
- get_current_user: 从 JWT 解析当前登录用户
- require_role: 角色鉴权依赖工厂
"""
from typing import Callable, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import verify_access_token
from app.db.session import SessionLocal, get_db
from app.models.user import User

# OAuth2 Bearer 令牌提取器, 指向登录接口
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 Bearer 令牌解析当前登录用户

    Raises:
        HTTPException 401: 令牌无效 / 用户不存在
        HTTPException 403: 账号已禁用
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据, 请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_access_token(token)
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            raise credentials_exc
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        raise credentials_exc
    except Exception:
        raise credentials_exc

    user = db.query(User).filter(User.Id == user_id, User.IsDeleted == False).first()
    if not user:
        raise credentials_exc
    if user.Status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用, 请联系管理员",
        )
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """角色鉴权依赖工厂

    用法:
        @router.post("/", dependencies=[Depends(require_role("admin"))])
        或
        def endpoint(current: User = Depends(require_role("admin", "lead_reviewer"))):
    """

    def checker(current: User = Depends(get_current_user)) -> User:
        if current.Role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足, 不允许执行此操作",
            )
        return current

    return checker


__all__ = ["SessionLocal", "get_db", "get_current_user", "require_role", "oauth2_scheme"]
