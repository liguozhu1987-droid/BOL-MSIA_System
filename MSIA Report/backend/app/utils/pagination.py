"""分页工具

提供基于 SQLAlchemy Query 的分页辅助函数。
"""
from typing import Any, List, Optional, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Query

from app.schemas.common import PageResponse

T = TypeVar("T", bound=Any)


def paginate(
    query: Query,
    page: int = 1,
    page_size: int = 20,
    schema: Optional[Type[BaseModel]] = None,
) -> PageResponse:
    """对 SQLAlchemy Query 执行分页

    Args:
        query: SQLAlchemy 查询对象 (已应用过滤/排序)
        page: 页码, 从 1 开始
        page_size: 每页数量
        schema: 可选的 Pydantic 模型, 用于序列化每条记录
    Returns:
        PageResponse: 包含 items / total / page / page_size / total_pages
    """
    page = max(page, 1)
    page_size = max(page_size, 1)

    total: int = query.count()
    total_pages = (total + page_size - 1) // page_size if total else 0

    items_query = query.limit(page_size).offset((page - 1) * page_size)
    raw_items: List[Any] = items_query.all()

    if schema is not None:
        items = [schema.model_validate(it, from_attributes=True) for it in raw_items]
    else:
        items = raw_items

    return PageResponse[schema or Any](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
