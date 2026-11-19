"""MSIA 计划路由

- 列表 / 详情 / 按工单查询关联信息
- 待评审项目快速查询 (本月/下月)
- 数据源为 HRDB (只读), 通过 HrdbQueryService 查询
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.config import Settings, settings as _settings
from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService

router = APIRouter(prefix="/api/msia-plan", tags=["MSIA计划"])


def _get_service() -> HrdbQueryService:
    """构造 HrdbQueryService 实例"""
    return HrdbQueryService(_settings)


def _batch_phase_scores(db: Session, plan_ids: list[str]) -> dict[str, dict[str, dict | None]]:
    """批量计算项目的 MSIA1~5 各阶段综合评分

    口径与工作台"我的项目库"一致:
    - 优先: ReviewRecord 中每个检查项的最新已提交评分记录, 按阶段求平均
    - 回退: 无逐条记录时取历史评分录入 (HistoricScore)
    - 未评审阶段值为 None (前端显示为空, 不做占位填充)

    返回 {planId: {"MSIA1": {...} | None, ..., "MSIA5": {...} | None}}
    """
    from app.models.review import ReviewRecord
    from app.models.historic_score import HistoricScore

    result: dict[str, dict[str, dict | None]] = {
        pid: {f"MSIA{i}": None for i in range(1, 6)} for pid in plan_ids
    }
    if not plan_ids:
        return result

    # 每个检查项 (plan, phase, item) 的最新评分记录 Id
    subq = (
        db.query(
            ReviewRecord.PlanId,
            ReviewRecord.PhaseCode,
            ReviewRecord.PhaseReviewItemId,
            sqlfunc.max(ReviewRecord.Id).label("max_id"),
        )
        .filter(
            ReviewRecord.PlanId.in_(plan_ids),
            ReviewRecord.Score.isnot(None),
        )
        .group_by(ReviewRecord.PlanId, ReviewRecord.PhaseCode, ReviewRecord.PhaseReviewItemId)
        .subquery()
    )
    rows = (
        db.query(subq.c.PlanId, subq.c.PhaseCode, ReviewRecord.Score)
        .join(ReviewRecord, ReviewRecord.Id == subq.c.max_id)
        .all()
    )
    # 聚合 (plan, phase) -> 评分列表
    scores_map: dict[tuple[str, str], list[float]] = {}
    for plan_id, phase_code, score in rows:
        if score is not None:
            scores_map.setdefault((plan_id, phase_code), []).append(float(score))
    for (plan_id, phase_code), scores in scores_map.items():
        if plan_id in result and phase_code in result[plan_id]:
            avg = sum(scores) / len(scores)
            result[plan_id][phase_code] = {
                "avg_score": round(avg, 4),
                "avg_percent": round(avg * 100, 1),
                "item_count": len(scores),
                "source": "review",
            }

    # 未覆盖的 (plan, phase) 回退历史评分录入
    missing = [
        (pid, ph)
        for pid in plan_ids
        for ph in result[pid]
        if result[pid][ph] is None
    ]
    if missing:
        h_rows = (
            db.query(HistoricScore.PlanId, HistoricScore.PhaseCode, HistoricScore.Score)
            .filter(
                HistoricScore.PlanId.in_(plan_ids),
                HistoricScore.Score.isnot(None),
            )
            .all()
        )
        for plan_id, phase_code, score in h_rows:
            if result.get(plan_id, {}).get(phase_code) is None:
                # 仅补未覆盖项 (历史评分优先级低于评审记录)
                result[plan_id][phase_code] = {
                    "avg_score": float(score),
                    "avg_percent": round(float(score) * 100, 1),
                    "item_count": 1,
                    "source": "historic",
                }
    return result


@router.get("/pending-reviews", summary="本月和下月待评审项目")
def list_pending_reviews(
    months_ahead: int = Query(1, ge=1, le=6, description="向后看的月数 (1=本月+下月)"),
    current: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """查询本月和下月需要评审但尚未完成的 MSIA 项目

    返回每个项目的待评审阶段列表 (pending_phases), 供审核员快速定位:
    - planId: 计划主键 (用于跳转项目详情)
    - pending_phases: [{phase: 'MSIA4', phase_num: 4, plan_date, days_until, is_overdue}]
    - 点击阶段可直接跳转至 /projects/{planId}/phases/{phase_num} 评审页面
    """
    service = _get_service()
    try:
        return service.query_pending_reviews(months_ahead=months_ahead)
    except Exception as exc:
        logger.exception("查询待评审项目失败: {}", exc)
        raise HTTPException(status_code=500, detail="查询待评审项目失败")


@router.get("", summary="MSIA计划列表")
def list_msia_plans(
    order_id: Optional[str] = Query(None, alias="order_id", description="工单 ID 精确过滤"),
    keyword: Optional[str] = Query(None, description="关键字模糊匹配"),
    page: int = Query(1, ge=1, description="页码, 从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询 MSIA 计划列表

    返回: { items, total, page, page_size, total_pages }
    每个 item 附带 phase_scores: MSIA1~5 各阶段综合评分 (未评审为 null)
    """
    service = _get_service()
    try:
        result = service.query_msia_plans(
            order_id=order_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            # 排除已完成全部阶段审核的归档项目 (在"项目存档"模块展示)
            exclude_archived=True,
        )
    except Exception as exc:
        logger.exception("查询 MSIA 计划列表失败: {}", exc)
        raise HTTPException(status_code=500, detail="查询 MSIA 计划列表失败")

    # 注入各阶段综合评分 (评分计算失败不影响列表本身)
    items = result.get("items", []) if isinstance(result, dict) else []
    plan_ids = [str(it.get("planId", "")).strip() for it in items if it.get("planId")]
    plan_ids = [pid for pid in plan_ids if pid]
    if plan_ids:
        try:
            scores = _batch_phase_scores(db, plan_ids)
            for it in items:
                pid = str(it.get("planId", "")).strip()
                if pid in scores:
                    it["phase_scores"] = scores[pid]
        except Exception as exc:
            logger.warning("项目列表阶段评分注入失败 (不影响列表): {}", exc)
    return result


@router.get("/order/{order_id}", summary="按工单ID查询关联信息")
def get_by_order_id(
    order_id: str,
    current: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """按工单 ID 查询关联信息

    返回工单基本信息 + 项目基本信息
    """
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id 不能为空")

    service = _get_service()
    try:
        order_info = service.query_order_basic_info(order_id)
        project_info = service.query_project_basic_info(order_id)
    except Exception as exc:
        logger.exception("按工单查询 MSIA 关联信息失败 orderId={}: {}", order_id, exc)
        raise HTTPException(status_code=500, detail="查询工单关联信息失败")

    if not order_info and not project_info:
        raise HTTPException(status_code=404, detail="未找到该工单相关的信息")

    return {
        "order_id": order_id,
        "order_basic_info": order_info,
        "project_basic_info": project_info,
    }


@router.get("/{plan_id}", summary="MSIA计划详情")
def get_msia_plan_detail(
    plan_id: str,
    current: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询单个 MSIA 计划详情

    返回计划详情 + 关联的工单信息 + 项目信息
    """
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id 不能为空")

    service = _get_service()
    try:
        detail = service.query_msia_plan_detail(plan_id)
    except Exception as exc:
        logger.exception("查询 MSIA 计划详情失败 plan_id={}: {}", plan_id, exc)
        raise HTTPException(status_code=500, detail="查询 MSIA 计划详情失败")

    if not detail:
        raise HTTPException(status_code=404, detail="MSIA 计划不存在")

    return detail
