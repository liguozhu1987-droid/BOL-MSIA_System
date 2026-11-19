"""审核记录数据模型"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    # 旧外键字段 (历史遗留, 已改为可空, 实际关联通过 PhaseReviewItemId + PlanId)
    ProjectId: Optional[int] = None
    PhaseId: Optional[int] = None
    ItemId: Optional[int] = None
    # 阶段评审检查项 ID (关联 PhaseReviewItem)
    PhaseReviewItemId: Optional[int] = None
    # 阶段代码 (MSIA1~MSIA5)
    PhaseCode: Optional[str] = Field(None, max_length=20)
    # 检查项编号 (冗余)
    ItemNo: Optional[str] = Field(None, max_length=50)
    # MSIA 计划 ID (关联具体项目)
    PlanId: Optional[str] = Field(None, max_length=100)
    Score: Optional[Decimal] = Field(None, description="评分 decimal 5,2")
    ResultText: Optional[str] = None
    Comments: Optional[str] = None
    Status: str = Field("draft", description="draft/submitted/confirmed")


class ReviewUpdate(BaseModel):
    Score: Optional[Decimal] = None
    ResultText: Optional[str] = None
    Comments: Optional[str] = None
    Status: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    ProjectId: Optional[int] = None
    PhaseId: Optional[int] = None
    ItemId: Optional[int] = None
    PhaseReviewItemId: Optional[int] = None
    PhaseCode: Optional[str] = None
    ItemNo: Optional[str] = None
    PlanId: Optional[str] = None
    ReviewerId: int
    Score: Optional[Decimal] = None
    ResultText: Optional[str] = None
    Comments: Optional[str] = None
    Status: str
    SubmittedAt: Optional[datetime] = None
    ConfirmedAt: Optional[datetime] = None
    ConfirmedBy: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None
