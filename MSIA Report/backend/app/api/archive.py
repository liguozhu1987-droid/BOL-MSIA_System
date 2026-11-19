"""项目存档路由

已完成全部阶段审核 (MSIA3/4/5 实际日期全部已维护 = 整体进度 100%) 的项目
从"MSIA计划"和"项目管理"模块移入本模块归档展示, 仅作历史数据查询:

- 归档项目列表: 含 MSIA1~5 各阶段评分 / 综合评分 / 问题统计
- 各阶段审核记录明细: 检查项内容 + 最新评分 + 评审意见 + 评审人

不提供评审/问题登记等写操作功能。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import case as sqlcase
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.config import Settings, settings as _settings
from app.core.deps import get_current_user, get_db
from app.models.issue import Issue
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService

router = APIRouter(prefix="/api/archive", tags=["项目存档"])

# 归档项目支持的阶段代码
_VALID_PHASES = {f"MSIA{i}" for i in range(1, 6)}


def _get_service() -> HrdbQueryService:
    return HrdbQueryService(_settings)


def _batch_issue_stats(db: Session, plan_ids: list[str]) -> dict[str, dict[str, int]]:
    """批量统计各归档项目的问题数量: {planId: {total, unclosed}}"""
    result: dict[str, dict[str, int]] = {pid: {"total": 0, "unclosed": 0} for pid in plan_ids}
    if not plan_ids:
        return result
    rows = (
        db.query(
            Issue.PlanId,
            sqlfunc.count(Issue.Id),
            sqlfunc.sum(sqlcase((Issue.Status != "closed", 1), else_=0)),
        )
        .filter(
            Issue.PlanId.in_(plan_ids),
            Issue.IsDeleted == False,  # noqa: E712
        )
        .group_by(Issue.PlanId)
        .all()
    )
    for plan_id, total, unclosed in rows:
        pid = str(plan_id).strip() if plan_id is not None else ""
        if pid in result:
            result[pid]["total"] = int(total or 0)
            result[pid]["unclosed"] = int(unclosed or 0)
    return result


@router.get("/projects", summary="归档项目列表")
def list_archived_projects(
    order_id: Optional[str] = Query(None, alias="order_id", description="工单 ID 精确过滤"),
    keyword: Optional[str] = Query(None, description="关键字模糊匹配"),
    page: int = Query(1, ge=1, description="页码, 从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询已完成全部阶段审核的归档项目

    返回: { items, total, page, page_size, total_pages }
    每个 item 附带:
    - phase_scores: MSIA1~5 各阶段综合评分 (口径与项目管理一致)
    - overall: 五个阶段综合评分的算术平均 (无任何评分时为 null)
    - issue_stats: {total, unclosed} 问题统计
    """
    from app.api.msia_plan import _batch_phase_scores

    service = _get_service()
    try:
        result = service.query_archived_plans(
            order_id=order_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        logger.exception("查询归档项目列表失败: {}", exc)
        raise HTTPException(status_code=500, detail="查询归档项目列表失败")

    items = result.get("items", []) if isinstance(result, dict) else []
    plan_ids = [str(it.get("planId", "")).strip() for it in items if it.get("planId")]
    plan_ids = [pid for pid in plan_ids if pid]

    # 注入各阶段综合评分 + 综合平均分
    if plan_ids:
        try:
            scores = _batch_phase_scores(db, plan_ids)
            for it in items:
                pid = str(it.get("planId", "")).strip()
                phase_scores = scores.get(pid)
                if phase_scores:
                    it["phase_scores"] = phase_scores
                    vals = [ps["avg_score"] for ps in phase_scores.values() if ps]
                    it["overall"] = round(sum(vals) / len(vals), 4) if vals else None
                else:
                    it["phase_scores"] = None
                    it["overall"] = None
        except Exception as exc:
            logger.warning("归档列表阶段评分注入失败 (不影响列表): {}", exc)

    # 注入问题统计
    if plan_ids:
        try:
            stats = _batch_issue_stats(db, plan_ids)
            for it in items:
                pid = str(it.get("planId", "")).strip()
                it["issue_stats"] = stats.get(pid, {"total": 0, "unclosed": 0})
        except Exception as exc:
            logger.warning("归档列表问题统计注入失败 (不影响列表): {}", exc)

    return result


@router.get("/projects/{plan_id}/reviews", summary="归档项目阶段审核记录")
def list_archived_phase_reviews(
    plan_id: str,
    phase_code: str = Query(..., description="阶段代码, 如 MSIA1"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询归档项目指定阶段的审核记录明细 (只读)

    返回该阶段全部检查项及其最新一条已提交评分记录:
    - items: [{seq, item_name, request, score, score_percent, result_text,
              comments, reviewer_name, submitted_at, status}]
      (无评分记录的检查项 score 为 null)
    - summary: {item_count, scored_count, avg_score, avg_percent}
    - historic_score: 无逐项评审记录时的历史补录阶段评分 (回退展示, 可为 null)
    """
    from app.models.historic_score import HistoricScore
    from app.models.phase_review_item import PhaseReviewItem
    from app.models.review import ReviewRecord

    phase_code = (phase_code or "").strip().upper()
    if phase_code not in _VALID_PHASES:
        raise HTTPException(status_code=400, detail=f"无效的阶段代码: {phase_code}")

    # 1) 该阶段全部检查项 (按清单顺序)
    items = (
        db.query(PhaseReviewItem)
        .filter(
            PhaseReviewItem.PhaseCode == phase_code,
            PhaseReviewItem.IsDeleted == False,  # noqa: E712
        )
        .order_by(PhaseReviewItem.Seq, PhaseReviewItem.SortOrder)
        .all()
    )

    # 2) 每个检查项的最新已提交评分记录 (该归档项目)
    subq = (
        db.query(
            ReviewRecord.PhaseReviewItemId,
            sqlfunc.max(ReviewRecord.Id).label("max_id"),
        )
        .filter(
            ReviewRecord.PlanId == plan_id,
            ReviewRecord.PhaseCode == phase_code,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
        )
        .group_by(ReviewRecord.PhaseReviewItemId)
        .subquery()
    )
    record_rows = (
        db.query(ReviewRecord, User)
        .join(subq, ReviewRecord.Id == subq.c.max_id)
        .outerjoin(User, User.Id == ReviewRecord.ReviewerId)
        .all()
    )
    record_map: dict[int, tuple] = {}
    for record, reviewer in record_rows:
        if record.PhaseReviewItemId is not None:
            record_map[record.PhaseReviewItemId] = (record, reviewer)

    # 3) 组装明细
    result_items: List[Dict[str, Any]] = []
    scored: list[float] = []
    for idx, item in enumerate(items, start=1):
        record_tuple = record_map.get(item.Id)
        score = None
        entry: Dict[str, Any] = {
            "seq": idx,
            "item_id": item.Id,
            "item_name": item.ItemName,
            "item_type": item.ItemType,
            "request": item.Request,
            "score": None,
            "score_percent": None,
            "result_text": None,
            "comments": None,
            "reviewer_name": None,
            "submitted_at": None,
        }
        if record_tuple:
            record, reviewer = record_tuple
            score = float(record.Score) if record.Score is not None else None
            reviewer_name = ""
            if reviewer:
                reviewer_name = (
                    reviewer.RealName or reviewer.DisplayName or reviewer.Username or ""
                )
            entry.update({
                "score": score,
                "score_percent": round(score * 100, 1) if score is not None else None,
                "result_text": record.ResultText,
                "comments": record.Comments,
                "reviewer_name": reviewer_name,
                "submitted_at": record.SubmittedAt.strftime("%Y-%m-%d %H:%M")
                if record.SubmittedAt
                else None,
            })
            if score is not None:
                scored.append(score)
        result_items.append(entry)

    avg_score = round(sum(scored) / len(scored), 4) if scored else None

    # 4) 无逐项记录时回退历史补录评分
    historic_score = None
    if not scored:
        h = (
            db.query(HistoricScore)
            .filter(
                HistoricScore.PlanId == plan_id,
                HistoricScore.PhaseCode == phase_code,
                HistoricScore.Score.isnot(None),
            )
            .order_by(HistoricScore.Id.desc())
            .first()
        )
        if h and h.Score is not None:
            historic_score = float(h.Score)

    return {
        "plan_id": plan_id,
        "phase_code": phase_code,
        "items": result_items,
        "summary": {
            "item_count": len(result_items),
            "scored_count": len(scored),
            "avg_score": avg_score,
            "avg_percent": round(avg_score * 100, 1) if avg_score is not None else None,
        },
        "historic_score": historic_score,
    }
