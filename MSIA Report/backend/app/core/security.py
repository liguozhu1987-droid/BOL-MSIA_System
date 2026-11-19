"""安全模块: JWT 令牌 + 密码哈希

- create_access_token: 创建 JWT (携带 subject + role)
- verify_access_token: 校验并解码 JWT
- hash_password / verify_password: bcrypt 密码哈希

注意: 直接使用 bcrypt 库 (passlib 与 bcrypt 4.x/5.x 存在兼容性问题)
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希"""
    # bcrypt 限制密码长度不超过 72 字节
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希值是否匹配"""
    if not plain or not hashed:
        return False
    try:
        pwd_bytes = plain.encode("utf-8")[:72]
        hash_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def create_access_token(subject: str, role: str, extra_claims: Dict[str, Any] = None) -> str:
    """创建 JWT 访问令牌

    Args:
        subject: 令牌主体 (通常为用户 Id)
        role: 用户角色
        extra_claims: 附加声明
    Returns:
        编码后的 JWT 字符串
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(token: str) -> Dict[str, Any]:
    """校验 JWT 令牌并返回载荷

    Raises:
        jwt.PyJWTError: 令牌无效或已过期
    """
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    return payload
