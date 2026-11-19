"""项目数据模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    Name: str = Field(..., max_length=255)
    Code: str = Field(..., max_length=100)
    Type: Optional[str] = None
    CmcAme: Optional[str] = None
    PlantMe: Optional[str] = None
    InalfaKickoff: Optional[datetime] = None
    SupplierKickoff: Optional[datetime] = None
    DesignFreeze: Optional[datetime] = None
    Pvp: Optional[datetime] = None
    InalfaSop: Optional[datetime] = None
    Status: str = Field("not_started", description="not_started/in_progress/completed")


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    Name: Optional[str] = None
    Code: Optional[str] = None
    Type: Optional[str] = None
    CmcAme: Optional[str] = None
    PlantMe: Optional[str] = None
    InalfaKickoff: Optional[datetime] = None
    SupplierKickoff: Optional[datetime] = None
    DesignFreeze: Optional[datetime] = None
    Pvp: Optional[datetime] = None
    InalfaSop: Optional[datetime] = None
    Status: Optional[str] = None


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    CreatedBy: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None
