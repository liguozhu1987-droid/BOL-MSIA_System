"""通用数据模型: 分页 / 统一响应"""
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageRequest(BaseModel):
    """分页请求基类"""
    page: int = Field(1, ge=1, description="页码, 从 1 开始")
    page_size: int = Field(20, ge=1, le=200, description="每页数量")
    keyword: Optional[str] = Field(None, description="关键字搜索")


class PageResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int = Field(0, description="总条数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页数量")
    total_pages: int = Field(0, description="总页数")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应包装"""
    code: int = Field(0, description="业务码: 0 表示成功, 非 0 表示错误")
    message: str = Field("success", description="提示信息")
    data: Optional[T] = None
