"""升级配置 schemas"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


SEVERITIES = ("H", "M", "L")


class EscalationConfigBase(BaseModel):
    Plant: str = Field(..., max_length=100, description="工厂名称 (如 CC/BJ/SH); '*' 表示全局兜底")
    Severity: str = Field(..., max_length=2, description="严重等级 H/M/L")
    Level1Hours: int = Field(
        48, ge=1, le=720,
        description="Lv1 逾期阈值(h): 逾期达到后首次提醒责任人, 之后每该间隔重复",
    )
    Level2Hours: int = Field(
        168, ge=1, le=720,
        description="Lv2 逾期阈值(h): 逾期达到后首次升级部门经理, 之后每该间隔重复",
    )
    Level3Hours: int = Field(
        336, ge=1, le=1440,
        description="Lv3 逾期阈值(h): 逾期达到后首次升级 AME Director, 之后每该间隔重复",
    )
    Level1Recipients: Optional[str] = Field(None, description="Level1 收件人 (留空使用责任人邮箱)")
    Level2Recipients: Optional[str] = Field(None, description="Level2 收件人 (部门经理, 分号分隔)")
    Level3Recipients: Optional[str] = Field(None, description="Level3 收件人 (AME Director, 分号分隔)")
    IsEnabled: bool = True
    Remarks: Optional[str] = None

    @model_validator(mode="after")
    def check_hours(self):
        if not (self.Level1Hours < self.Level2Hours < self.Level3Hours):
            raise ValueError("触发小时数须满足 Level1Hours < Level2Hours < Level3Hours")
        if self.Severity not in SEVERITIES:
            raise ValueError(f"Severity 必须是 {SEVERITIES} 之一")
        return self


class EscalationConfigCreate(EscalationConfigBase):
    pass


class EscalationConfigUpdate(BaseModel):
    Plant: Optional[str] = Field(
        None, max_length=100, description="工厂名称 (如 CC/BJ/SH); '*' 表示全局兜底"
    )
    Severity: Optional[str] = Field(None, max_length=2, description="严重等级 H/M/L")
    Level1Hours: Optional[int] = Field(None, ge=1, le=720)
    Level2Hours: Optional[int] = Field(None, ge=1, le=720)
    Level3Hours: Optional[int] = Field(None, ge=1, le=1440)
    Level1Recipients: Optional[str] = None
    Level2Recipients: Optional[str] = None
    Level3Recipients: Optional[str] = None
    IsEnabled: Optional[bool] = None
    Remarks: Optional[str] = None


class EscalationConfigOut(EscalationConfigBase):
    model_config = ConfigDict(from_attributes=True)

    Id: int
    CreatedBy: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


class EscalationLogOut(BaseModel):
    """升级日志输出"""
    model_config = ConfigDict(from_attributes=True)

    Id: int
    IssueId: int
    ConfigId: Optional[int] = None
    Level: int
    RemindCount: Optional[int] = None
    # 实际发送邮箱 (测试模式下为重定向后的测试邮箱)
    Recipients: str
    # 原始收件人 (测试模式重定向前; 生产模式下与 Recipients 相同)
    OriginalRecipients: Optional[str] = None
    EmailLogId: Optional[int] = None
    SentAt: datetime
    # 扩展字段 (API 注入)
    IssueNo: Optional[str] = None
    IssueTitle: Optional[str] = None
    Plant: Optional[str] = None
    Severity: Optional[str] = None
    OwnerName: Optional[str] = None
    ProjectName: Optional[str] = None


class EscalationLogStatsOut(BaseModel):
    """升级统计"""
    total: int = 0
    level1_count: int = 0
    level2_count: int = 0
    level3_count: int = 0
    last_24h_count: int = 0


class TestEmailRequest(BaseModel):
    """测试邮件连通性请求"""
    recipient: str = Field(..., description="测试收件人邮箱地址")


class TestEmailResponse(BaseModel):
    """测试邮件连通性响应"""
    ok: bool
    message: str
    smtp_host: str
    smtp_port: int
    from_address: str
    log_id: Optional[int] = None
    error: Optional[str] = None
