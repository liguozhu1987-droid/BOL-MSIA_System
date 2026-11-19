"""历史评分录入路由

用于将系统上线前已审核完成的项目各阶段评分值直接录入系统。
仅 admin / lead_reviewer 可操作。

- GET  /api/historic-scores/projects         项目列表 (来自 HRDB, 含已录入评分)
- GET  /api/historic-scores/{plan_id}        查询某项目已录入的各阶段评分
- POST /api/historic-scores/{plan_id}        保存某项目各阶段评分 (upsert)
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.historic_score import HistoricScore
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService

router = APIRouter(prefix="/api/historic-scores", tags=["历史评分录入"])


def _get_hrdb_service() -> HrdbQueryService:
    return HrdbQueryService(settings)


# ============ Pydantic 模型 ============

class PhaseScoreIn(BaseModel):
    """单个阶段评分"""
    phase_code: str = Field(..., max_length=20, description="阶段代码, 如 MSIA1")
    score: float = Field(..., ge=0, le=100, description="评分百分比 0~100, 如 78 表示 78%")
    remark: str | None = Field(None, description="备注")


class HistoricScoreSave(BaseModel):
    """保存某项目各阶段评分"""
    order_id: str | None = Field(None, max_length=100)
    project_name: str | None = Field(None, max_length=500)
    scores: list[PhaseScoreIn] = Field(default_factory=list)


# ============ 路由 ============

@router.get("/projects", summary="项目列表 (含已录入历史评分)")
def list_projects(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """列出 MSIA 计划中的项目, 并标注哪些项目已录入历史评分"""
    service = _get_hrdb_service()
    try:
        result = service.query_msia_plans(
            keyword=keyword,
            order_id=None,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 MSIA 计划列表失败: {exc}")

    items = result.get("items", [])
    plan_ids = [str(it.get("planId")) for it in items if it.get("planId")]

    # 批量查询已录入的历史评分
    scores_by_plan: dict[str, list[dict]] = {}
    if plan_ids:
        rows = (
            db.query(HistoricScore)
            .filter(HistoricScore.PlanId.in_(plan_ids))
            .all()
        )
        for r in rows:
            scores_by_plan.setdefault(r.PlanId, []).append({
                "phase_code": r.PhaseCode,
                "score": float(r.Score),
                # round 消除浮点误差: 0.58 * 100 = 57.99999999999999
                "score_percent": round(float(r.Score) * 100, 2),
                "remark": r.Remark,
            })

    # 组装返回
    enriched = []
    for it in items:
        pid = str(it.get("planId"))
        plan_scores = scores_by_plan.get(pid, [])
        # 已录入的阶段
        entered_phases = {s["phase_code"]: s for s in plan_scores}
        enriched.append({
            "planId": it.get("planId"),
            "orderId": it.get("orderId"),
            "projectName": it.get("projectName"),
            "order_description": it.get("order_description"),
            "lineType": it.get("lineType"),
            "ownerName": it.get("ownerName"),
            "leadUser": it.get("leadUser"),
            "plantName": it.get("plantName"),
            "lineName": it.get("lineName"),
            "issueDate": it.get("issueDate"),
            "endDate": it.get("endDate"),
            "entered_scores": plan_scores,
            "entered_phase_count": len(plan_scores),
            "entered_phases_map": entered_phases,
        })

    return {
        "items": enriched,
        "total": result.get("total", len(enriched)),
        "page": result.get("page", page),
        "page_size": result.get("page_size", page_size),
        "total_pages": result.get("total_pages", 0),
    }


@router.get("/{plan_id}", summary="查询某项目已录入的各阶段评分")
def get_project_scores(
    plan_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    rows = (
        db.query(HistoricScore)
        .filter(HistoricScore.PlanId == str(plan_id))
        .order_by(HistoricScore.PhaseCode)
        .all()
    )
    return [
        {
            "id": r.Id,
            "plan_id": r.PlanId,
            "phase_code": r.PhaseCode,
            "score": float(r.Score),
            "score_percent": round(float(r.Score) * 100, 2),
            "remark": r.Remark,
            "created_at": r.CreatedAt,
            "updated_at": r.UpdatedAt,
        }
        for r in rows
    ]


@router.post("/{plan_id}", summary="保存某项目各阶段评分 (upsert)", dependencies=[Depends(require_role("admin", "lead_reviewer"))])
def save_project_scores(
    plan_id: str,
    payload: HistoricScoreSave,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """保存某项目各阶段历史评分

    - 按 (PlanId, PhaseCode) 唯一键 upsert
    - 前端可只提交需要录入的阶段
    """
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id 不能为空")

    saved = []
    for item in payload.scores:
        phase_code = item.phase_code.strip()
        if not phase_code:
            continue
        # 百分比 0-100 → 小数 0-1 (与 ReviewRecord.Score 格式一致)
        score_decimal = Decimal(str(round(item.score, 2))) / Decimal("100")

        existing = (
            db.query(HistoricScore)
            .filter(
                HistoricScore.PlanId == str(plan_id),
                HistoricScore.PhaseCode == phase_code,
            )
            .first()
        )
        if existing:
            existing.Score = score_decimal
            existing.Remark = item.remark
            existing.OrderId = payload.order_id
            existing.ProjectName = payload.project_name
        else:
            existing = HistoricScore(
                PlanId=str(plan_id),
                PhaseCode=phase_code,
                Score=score_decimal,
                Remark=item.remark,
                OrderId=payload.order_id,
                ProjectName=payload.project_name,
                CreatedBy=current.Id,
            )
            db.add(existing)
        saved.append(phase_code)

    db.commit()
    return {"ok": True, "plan_id": plan_id, "saved_phases": saved}


@router.delete("/{plan_id}/{phase_code}", summary="删除某阶段历史评分", dependencies=[Depends(require_role("admin", "lead_reviewer"))])
def delete_project_score(
    plan_id: str,
    phase_code: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = (
        db.query(HistoricScore)
        .filter(
            HistoricScore.PlanId == str(plan_id),
            HistoricScore.PhaseCode == phase_code,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="该阶段历史评分不存在")
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "历史评分已删除"}
