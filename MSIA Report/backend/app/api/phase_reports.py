"""MSIA 阶段审核报告路由 (按 Report MSIA 模板格式)

- GET  /api/projects/{plan_id}/phase-report/{phase_code}
      阶段审核报告数据 (JSON): 关键数据/高风险问题/检查项评分与问题/评审信息
- GET  /api/projects/{plan_id}/phase-report/{phase_code}/export
      导出阶段审核报告 PDF (模板格式)
- GET  /api/projects/{plan_id}/phase-review-meta/{phase_code}
      查询阶段评审元数据 (Review place)
- PUT  /api/projects/{plan_id}/phase-review-meta/{phase_code}
      维护阶段评审元数据 (仅审核员: admin/lead_reviewer/reviewer)
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.phase_review_meta import PhaseReviewMeta
from app.models.user import User
from app.services.phase_report_service import (
    build_combined_report,
    build_phase_report,
    generate_combined_report_pdf,
    generate_phase_report_pdf,
)

router = APIRouter(prefix="/api", tags=["阶段审核报告"])

_VALID_PHASES = {"MSIA1", "MSIA2", "MSIA3", "MSIA4", "MSIA5"}


def _validate_phase(phase_code: str) -> str:
    code = phase_code.strip().upper()
    if code not in _VALID_PHASES:
        raise HTTPException(status_code=400, detail=f"无效的阶段代码: {phase_code}, 应为 MSIA1~MSIA5")
    return code


@router.get(
    "/projects/{plan_id}/phase-report/{phase_code}",
    summary="获取阶段审核报告数据 (模板格式)",
)
def get_phase_audit_report(
    plan_id: str,
    phase_code: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """按 Report MSIA 模板构建阶段审核报告:
    - 头部: 项目关键数据 + 里程碑 + MSIA No. + MSIA Result
    - High-risk comments: Severity/Priority = H 的问题
    - 检查项: Result (最新评分, 未评分为空) + Comment (该检查项问题逐条)
    - 尾部: Reviewers (评分+提问题用户) / Review place / Reviewees / Date
    """
    code = _validate_phase(phase_code)
    return build_phase_report(db, settings, plan_id, code)


@router.get(
    "/projects/{plan_id}/phase-report/{phase_code}/export",
    summary="导出阶段审核报告 (PDF)",
)
def export_phase_audit_report(
    plan_id: str,
    phase_code: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    code = _validate_phase(phase_code)
    try:
        report = build_phase_report(db, settings, plan_id, code)
        pdf_bytes = generate_phase_report_pdf(report)
    except Exception as exc:
        logger.exception("生成阶段审核报告 PDF 失败: plan={} phase={}", plan_id, code)
        raise HTTPException(status_code=500, detail=f"报告生成失败: {exc}")
    filename = f"MSIA_report_{plan_id}_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============ 阶段评审元数据 (Review place 手动维护) ============

# ============ 合并审核报告 (MSIA1+2+3 汇总) ============

@router.get(
    "/projects/{plan_id}/combined-report",
    summary="获取合并审核报告数据 (多阶段汇总)",
)
def get_combined_audit_report(
    plan_id: str,
    phases: str = "MSIA1,MSIA2,MSIA3",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """构建多阶段合并审核报告 (如 MSIA1+MSIA2+MSIA3 汇总):
    - 头部 (Project Key Data + Milestones) 合并
    - High-risk comments 合并
    - 检查项表格按阶段竖直叠加, 各阶段保留 Reviewers/Reviewees/Date
    - MSIA Result: 各阶段平均分的算数平均
    """
    phase_list = [p.strip().upper() for p in phases.split(",") if p.strip()]
    for p in phase_list:
        if p not in _VALID_PHASES:
            raise HTTPException(status_code=400, detail=f"无效的阶段代码: {p}")
    return build_combined_report(db, settings, plan_id, phase_list)


@router.get(
    "/projects/{plan_id}/combined-report/export",
    summary="导出合并审核报告 PDF (多阶段汇总)",
)
def export_combined_audit_report(
    plan_id: str,
    phases: str = "MSIA1,MSIA2,MSIA3",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    phase_list = [p.strip().upper() for p in phases.split(",") if p.strip()]
    for p in phase_list:
        if p not in _VALID_PHASES:
            raise HTTPException(status_code=400, detail=f"无效的阶段代码: {p}")
    try:
        report = build_combined_report(db, settings, plan_id, phase_list)
        pdf_bytes = generate_combined_report_pdf(report)
    except Exception as exc:
        logger.exception("生成合并审核报告 PDF 失败: plan={} phases={}", plan_id, phase_list)
        raise HTTPException(status_code=500, detail=f"报告生成失败: {exc}")
    label = "+".join(p.replace("MSIA", "") for p in phase_list)
    filename = f"MSIA_report_{plan_id}_combined_{label}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============ 阶段评审元数据 (Review place 手动维护) ============

class PhaseReviewMetaOut(BaseModel):
    plan_id: str
    phase_code: str
    review_place: str
    cmc_ame: str = ""
    inalfa_kickoff: str = ""
    supplier_kickoff: str = ""
    design_freeze: str = ""
    pvp: str = ""
    inalfa_sop: str = ""
    updated_at: Optional[datetime] = None


class PhaseReviewMetaUpdate(BaseModel):
    review_place: Optional[str] = Field(None, min_length=1, max_length=500, description="评审地点 (如 Teams)")
    cmc_ame: Optional[str] = Field(None, max_length=255, description="CMC AME (项目级, 默认为空, 同步所有阶段)")
    inalfa_kickoff: Optional[str] = Field(None, max_length=50, description="Inalfa kick-off 时间点 (项目级)")
    supplier_kickoff: Optional[str] = Field(None, max_length=50, description="Supplier kick-off 时间点 (项目级)")
    design_freeze: Optional[str] = Field(None, max_length=50, description="Design freeze 时间点 (项目级)")
    pvp: Optional[str] = Field(None, max_length=50, description="PVP 时间点 (项目级)")
    inalfa_sop: Optional[str] = Field(None, max_length=50, description="Inalfa SOP 时间点 (项目级)")


def _get_or_init_meta(db: Session, plan_id: str, phase_code: str) -> PhaseReviewMeta:
    meta = (
        db.query(PhaseReviewMeta)
        .filter(
            PhaseReviewMeta.PlanId == str(plan_id),
            PhaseReviewMeta.PhaseCode == phase_code,
        )
        .first()
    )
    if not meta:
        meta = PhaseReviewMeta(
            PlanId=str(plan_id),
            PhaseCode=phase_code,
            ReviewPlace="Teams",
        )
        db.add(meta)
        db.commit()
        db.refresh(meta)
    return meta


def _meta_out(meta: PhaseReviewMeta, plan_id: str, phase_code: str) -> PhaseReviewMetaOut:
    return PhaseReviewMetaOut(
        plan_id=str(plan_id),
        phase_code=phase_code,
        review_place=meta.ReviewPlace or "Teams",
        cmc_ame=meta.CmcAme or "",
        inalfa_kickoff=meta.InalfaKickoff or "",
        supplier_kickoff=meta.SupplierKickoff or "",
        design_freeze=meta.DesignFreeze or "",
        pvp=meta.Pvp or "",
        inalfa_sop=meta.InalfaSop or "",
        updated_at=meta.UpdatedAt,
    )


@router.get(
    "/projects/{plan_id}/phase-review-meta/{phase_code}",
    response_model=PhaseReviewMetaOut,
    summary="查询阶段评审元数据 (Review place / CMC AME / Milestones)",
)
def get_phase_review_meta(
    plan_id: str,
    phase_code: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    code = _validate_phase(phase_code)
    meta = _get_or_init_meta(db, plan_id, code)
    return _meta_out(meta, plan_id, code)


@router.put(
    "/projects/{plan_id}/phase-review-meta/{phase_code}",
    response_model=PhaseReviewMetaOut,
    summary="维护阶段评审元数据 (仅审核员)",
)
def update_phase_review_meta(
    plan_id: str,
    phase_code: str,
    payload: PhaseReviewMetaUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin", "lead_reviewer", "reviewer")),
):
    """在报告弹窗中手动维护评审元数据

    - review_place: 阶段级, 仅写入当前阶段
    - cmc_ame / 里程碑 (Inalfa kick-off 等 5 项): 项目级,
      同步写入同项目 MSIA1~MSIA5 全部阶段, 保证各阶段报告一致
    """
    code = _validate_phase(phase_code)
    values = payload.model_dump()
    if all(v is None for v in values.values()):
        raise HTTPException(status_code=400, detail="至少提供一个待维护字段")

    meta = _get_or_init_meta(db, plan_id, code)
    if values["review_place"] is not None:
        meta.ReviewPlace = values["review_place"].strip()
    meta.UpdatedBy = current.Id

    # 项目级字段: CMC AME + 5 个里程碑, 同步到同项目所有阶段
    # payload 字段名 (snake_case) -> 模型属性名 (PascalCase)
    field_to_attr = {
        "cmc_ame": "CmcAme",
        "inalfa_kickoff": "InalfaKickoff",
        "supplier_kickoff": "SupplierKickoff",
        "design_freeze": "DesignFreeze",
        "pvp": "Pvp",
        "inalfa_sop": "InalfaSop",
    }
    project_level = {
        field_to_attr[k]: v
        for k, v in values.items()
        if k in field_to_attr and v is not None
    }
    if project_level:
        all_codes = ["MSIA1", "MSIA2", "MSIA3", "MSIA4", "MSIA5"]
        existing = {
            m.PhaseCode: m
            for m in db.query(PhaseReviewMeta)
            .filter(PhaseReviewMeta.PlanId == str(plan_id))
            .all()
        }
        for pc in all_codes:
            m = existing.get(pc)
            if not m:
                m = PhaseReviewMeta(
                    PlanId=str(plan_id),
                    PhaseCode=pc,
                    ReviewPlace="Teams",
                )
                db.add(m)
            for attr, val in project_level.items():
                setattr(m, attr, val.strip())
            m.UpdatedBy = current.Id

    db.commit()
    db.refresh(meta)
    return _meta_out(meta, plan_id, code)
