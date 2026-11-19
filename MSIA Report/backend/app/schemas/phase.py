"""阶段数据模型"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PhaseUpdate(BaseModel):
    Name: Optional[str] = None
    TimingDescription: Optional[str] = None
    MainTargets: Optional[str] = None
    Status: Optional[str] = Field(None, description="not_started/in_progress/completed")
    LeadReviewerId: Optional[int] = None
    Score: Optional[Decimal] = Field(None, description="阶段评分 decimal 5,2")


class PhaseConfirmRequest(BaseModel):
    """阶段确认请求"""
    Score: Optional[Decimal] = None


class PhaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    ProjectId: int
    Code: str
    Name: Optional[str] = None
    TimingDescription: Optional[str] = None
    MainTargets: Optional[str] = None
    Status: str
    LeadReviewerId: Optional[int] = None
    Score: Optional[Decimal] = None
    CompletedAt: Optional[datetime] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None
