"""数据库会话

- engine: SQLAlchemy 引擎 (SQL Server via pyodbc)
- SessionLocal: 会话工厂
- get_db: FastAPI 依赖, 生成数据库会话
- create_tables: 建表 (开发用, 生产建议用迁移工具)
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# SQL Server 引擎; pool_pre_ping 防止连接失效; fast_executemany 提升批量插入性能
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    fast_executemany=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖: 生成数据库会话并在请求结束后关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """根据模型元数据创建所有表 (开发/演示用)

    生产环境推荐使用 Alembic 进行迁移管理。
    """
    # 导入所有模型以确保它们被注册到 Base.metadata
    from app.models import (  # noqa: F401
        attachment,
        check_item,
        email_log,
        escalation_config,
        historic_score,
        issue,
        issue_comment,
        notification,
        phase_review_item,
        project,
        record_entry,
        review,
        user,
    )
    from app.models.base import Base

    Base.metadata.create_all(bind=engine)
