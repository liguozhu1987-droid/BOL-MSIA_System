"""审核记录路由"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.check_item import CheckItem
from app.models.historic_score import HistoricScore
from app.models.phase_review_item import PhaseReviewItem
from app.models.review import ReviewRecord
from app.models.user import User
from app.schemas.common import PageResponse
from app.schemas.review import ReviewCreate, ReviewOut, ReviewUpdate
from app.services.score_control_service import backfill_score_after_update
from app.utils.pagination import paginate
from app.utils.time import now_cst

router = APIRouter(prefix="/api", tags=["审核记录"])


def _visible_review_item_ids(db: Session, phase_code: str) -> set[int]:
    """当前评审清单可见的检查项 Id 集合 (与 /phase-review-items 接口同口径)

    自愈过滤: 剔除 CheckItemId 指向已删除/停用审核标准的条目,
    确保评分统计 (count/avg) 与界面显示的检查项清单一致。
    """
    items = (
        db.query(PhaseReviewItem.Id, PhaseReviewItem.CheckItemId)
        .filter(
            PhaseReviewItem.PhaseCode == phase_code,
            PhaseReviewItem.IsDeleted == False,  # noqa: E712
        )
        .all()
    )
    active_check_ids = {
        row[0]
        for row in db.query(CheckItem.Id)
        .filter(
            CheckItem.PhaseCode == phase_code,
            CheckItem.IsDeleted == False,  # noqa: E712
            CheckItem.IsActive != False,  # noqa: E712
        )
        .all()
    }
    return {
        item_id
        for item_id, check_id in items
        if check_id is None or check_id in active_check_ids
    }


@router.get("/reviews/phase-result", summary="阶段评审平均分 (MSIA Result)")
def get_phase_result(
    phase_code: str = Query(..., description="阶段代码, 如 MSIA1"),
    plan_id: str = Query(None, description="MSIA 计划 ID, 按项目过滤"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict[str, Any]:
    """计算指定阶段的评审平均分

    规则: 只考虑有分数的检查项 (0% 也计算在内), 未评分 (Score 为空) 的不参与计算。
    若同一 (项目, 检查项) 有多条评审记录, 取最新一条; 全局统计 (不带 plan_id) 时
    各项目的评分均独立参与计算, 不会相互覆盖。
    仅统计当前评审清单中可见的检查项 (与界面清单同口径, 剔除关联已停用/删除
    审核标准的条目), 确保 count 与界面检查项数量对应。
    """
    visible_ids = _visible_review_item_ids(db, phase_code)
    if not visible_ids:
        return {"phase_code": phase_code, "plan_id": plan_id, "avg_score": None, "count": 0}

    # 子查询: 每个 (项目, 检查项) 的最新评审记录 (限可见检查项)
    subq = (
        db.query(
            ReviewRecord.PlanId,
            ReviewRecord.PhaseReviewItemId,
            sqlfunc.max(ReviewRecord.Id).label("max_id"),
        )
        .filter(
            ReviewRecord.PhaseCode == phase_code,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.PhaseReviewItemId.in_(visible_ids),
        )
    )
    if plan_id:
        subq = subq.filter(ReviewRecord.PlanId == str(plan_id))
    subq = subq.group_by(ReviewRecord.PlanId, ReviewRecord.PhaseReviewItemId).subquery()

    # 关联主表取分数
    records = (
        db.query(ReviewRecord.Score)
        .join(subq, ReviewRecord.Id == subq.c.max_id)
        .all()
    )

    scores = [float(r.Score) for r in records if r.Score is not None]
    if not scores:
        return {"phase_code": phase_code, "plan_id": plan_id, "avg_score": None, "count": 0}

    avg = sum(scores) / len(scores)
    return {
        "phase_code": phase_code,
        "plan_id": plan_id,
        "avg_score": round(avg, 4),
        "count": len(scores),
    }


@router.get("/reviews/phase-results", summary="多阶段评审平均分 (批量)")
def get_phase_results_batch(
    plan_id: str = Query(..., description="MSIA 计划 ID"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """批量查询 MSIA1~5 各阶段的评审平均分 (用于项目管理页面指标卡)

    若某阶段无逐条评审记录 (系统上线前已审核完成), 则回退到历史评分录入值。
    """
    results: list[dict[str, Any]] = []
    for i in range(1, 6):
        phase_code = f"MSIA{i}"
        # 仅统计当前评审清单中可见的检查项 (与界面清单同口径)
        visible_ids = _visible_review_item_ids(db, phase_code)
        subq = (
            db.query(
                ReviewRecord.PhaseReviewItemId,
                sqlfunc.max(ReviewRecord.Id).label("max_id"),
            )
            .filter(
                ReviewRecord.PhaseCode == phase_code,
                ReviewRecord.Score.isnot(None),
                ReviewRecord.PlanId == str(plan_id),
                ReviewRecord.PhaseReviewItemId.in_(visible_ids) if visible_ids else sqlfunc.literal(False),
            )
            .group_by(ReviewRecord.PhaseReviewItemId)
            .subquery()
        )
        records = (
            db.query(ReviewRecord.Score)
            .join(subq, ReviewRecord.Id == subq.c.max_id)
            .all()
        )
        scores = [float(r.Score) for r in records if r.Score is not None]
        if scores:
            avg = sum(scores) / len(scores)
            results.append({
                "phase_code": phase_code,
                "avg_score": round(avg, 4),
                "count": len(scores),
                "source": "review",
            })
        else:
            # 无逐条评审记录, 回退到历史评分录入
            historic = (
                db.query(HistoricScore)
                .filter(
                    HistoricScore.PlanId == str(plan_id),
                    HistoricScore.PhaseCode == phase_code,
                )
                .first()
            )
            if historic:
                results.append({
                    "phase_code": phase_code,
                    "avg_score": float(historic.Score),
                    "count": 1,
                    "source": "historic",
                })
            else:
                results.append({
                    "phase_code": phase_code,
                    "avg_score": None,
                    "count": 0,
                    "source": None,
                })
    return results


@router.get("/reviews/phase-items-latest", summary="阶段各检查项最新评审记录 (批量)")
def get_phase_items_latest(
    phase_code: str = Query(..., description="阶段代码, 如 MSIA1"),
    plan_id: str = Query(None, description="MSIA 计划 ID, 按项目过滤"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """批量查询指定阶段下所有检查项的最新评审记录 (用于评审检查项清单 RESULT 列展示)

    规则:
      - 取每个 PhaseReviewItemId 的最新一条评审记录 (按 Id desc)
      - 返回 [{phase_review_item_id, score, comments, status, updated_at}, ...]
      - 多次评审以最新一次为准
    """
    # 子查询: 每个检查项的最新评审记录 Id (不考虑 Score 是否为空, 以便显示评审状态)
    subq = (
        db.query(
            ReviewRecord.PhaseReviewItemId,
            sqlfunc.max(ReviewRecord.Id).label("max_id"),
        )
        .filter(ReviewRecord.PhaseCode == phase_code)
    )
    if plan_id:
        subq = subq.filter(ReviewRecord.PlanId == str(plan_id))
    subq = subq.group_by(ReviewRecord.PhaseReviewItemId).subquery()

    # 关联主表取记录详情
    records = (
        db.query(
            ReviewRecord.Id,
            ReviewRecord.PhaseReviewItemId,
            ReviewRecord.Score,
            ReviewRecord.Status,
            ReviewRecord.UpdatedAt,
            ReviewRecord.Comments,
        )
        .join(subq, ReviewRecord.Id == subq.c.max_id)
        .all()
    )

    return [
        {
            "phase_review_item_id": r.PhaseReviewItemId,
            "review_id": r.Id,
            "score": float(r.Score) if r.Score is not None else None,
            "status": r.Status,
            "comments": r.Comments,
            "updated_at": r.UpdatedAt,
        }
        for r in records
    ]


@router.get("/projects/{project_id}/reviews", response_model=PageResponse[ReviewOut], summary="项目下审核记录")
def list_project_reviews(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(ReviewRecord).filter(ReviewRecord.ProjectId == project_id)
    query = query.order_by(ReviewRecord.Id.desc())
    return paginate(query, page, page_size, schema=ReviewOut)


@router.get("/phases/{phase_id}/reviews", response_model=PageResponse[ReviewOut], summary="阶段下审核记录")
def list_phase_reviews(
    phase_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(ReviewRecord).filter(ReviewRecord.PhaseId == phase_id)
    query = query.order_by(ReviewRecord.Id.desc())
    return paginate(query, page, page_size, schema=ReviewOut)


@router.get("/phase-review-items/{item_id}/reviews", response_model=list[ReviewOut], summary="检查项下所有评审记录")
def list_item_reviews(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """按 PhaseReviewItemId 查询该检查项的所有评审记录"""
    records = (
        db.query(ReviewRecord)
        .filter(ReviewRecord.PhaseReviewItemId == item_id)
        .order_by(ReviewRecord.Id.desc())
        .all()
    )
    return records


@router.post("/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED, summary="创建审核记录")
def create_review(payload: ReviewCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    # 权限: 仅审核员 (admin/lead_reviewer/reviewer) 可创建评审记录, 被审核员不可
    if current.Role not in ("admin", "lead_reviewer", "reviewer"):
        raise HTTPException(status_code=403, detail="被审核人员无权创建评审记录, 仅审核员可评分")
    record = ReviewRecord(
        **payload.model_dump(),
        ReviewerId=current.Id,
    )
    if record.Status == "submitted":
        record.SubmittedAt = now_cst()
    db.add(record)
    db.commit()
    db.refresh(record)
    # 评分管控: 提交评分后, 回写该检查项下已关闭问题的整改后评分
    if record.Score is not None and record.Status in ("submitted", "confirmed"):
        backfill_score_after_update(db, record.PlanId, record.PhaseReviewItemId)
        db.commit()
    return record


@router.put("/reviews/{review_id}", response_model=ReviewOut, summary="更新审核记录")
def update_review(
    review_id: int,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # 权限: 仅审核员 (admin/lead_reviewer/reviewer) 可更新评审记录
    if current.Role not in ("admin", "lead_reviewer", "reviewer"):
        raise HTTPException(status_code=403, detail="被审核人员无权修改评审记录, 仅审核员可评分")
    record = db.query(ReviewRecord).filter(ReviewRecord.Id == review_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    # 权限: 仅作者或 admin/lead_reviewer 可更新
    if record.ReviewerId != current.Id and current.Role not in ("admin", "lead_reviewer"):
        raise HTTPException(status_code=403, detail="无权修改他人的评审记录")
    data = payload.model_dump(exclude_unset=True)
    if data.get("Status") == "submitted" and not record.SubmittedAt:
        record.SubmittedAt = now_cst()
    if data.get("Status") == "confirmed":
        record.ConfirmedAt = now_cst()
        record.ConfirmedBy = current.Id
    for k, v in data.items():
        setattr(record, k, v)
    db.commit()
    db.refresh(record)
    # 评分管控: 评分提交/更新后, 回写该检查项下已关闭问题的整改后评分
    if record.Score is not None and record.Status in ("submitted", "confirmed"):
        backfill_score_after_update(db, record.PlanId, record.PhaseReviewItemId)
        db.commit()
    return record


@router.delete("/reviews/{review_id}", summary="删除审核记录", dependencies=[Depends(require_role("admin", "lead_reviewer"))])
def delete_review(review_id: int, db: Session = Depends(get_db)):
    record = db.query(ReviewRecord).filter(ReviewRecord.Id == review_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    db.delete(record)
    db.commit()
    return {"message": "审核记录已删除"}
