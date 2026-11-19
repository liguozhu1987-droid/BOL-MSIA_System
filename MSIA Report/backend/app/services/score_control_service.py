"""评分管控服务 (问题关闭 → 审核条款评分更新闭环)

机制:
1. 问题关闭时 (任何入口) → 快照该检查项当时的最新评分为 ScoreAtClosure (整改前评分)
2. 审核员对该检查项重新评分时 → 覆盖式回写 ScoreAfterUpdate (整改后评分) + ScoreUpdatedAt
   (始终取最新评分, 保证修正评分不被吞掉)
3. 已关闭且 ScoreAfterUpdate 为空的问题 → 前端显示"待更新评分"
4. 已关闭问题可重开 (reopen): 评分管控三字段全部清零, 重新走完整闭环

统一入口约束: 关闭问题一律调用 close_issue_with_snapshot, 重开一律调用
reopen_issue_and_reset_scores, 禁止在 API 层直接写 issue.Status = "closed"。

由此实现: 整改前评分 → 整改完成 → 整改后评分 (可修正) 的完整管控链路。
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.issue import Issue
from app.models.review import ReviewRecord
from app.models.user import User
from app.utils.time import now_cst


def close_issue_with_snapshot(
    db: Session,
    issue: Issue,
    *,
    operator: User | None = None,
    verification_comments: str | None = None,
    closing_status: str | None = None,
) -> None:
    """统一关闭入口 (系统内唯一合法的关闭方式)

    原子完成: Status=closed + ClosedAt + VerifiedBy/At (如有 operator)
    + 快照评分 + 清理关闭申请字段 (重开后再关闭需重新申请)。

    所有关闭路径 (审批关闭 / 状态变更 / 验证关闭 / 编辑关闭) 必须调用本函数,
    保证 ScoreAtClosure 快照不遗漏。
    """
    issue.Status = "closed"
    issue.ClosedAt = now_cst()
    if operator is not None:
        issue.VerifiedBy = operator.Id
        issue.VerifiedAt = issue.ClosedAt
    if verification_comments:
        issue.VerificationComments = verification_comments
    if closing_status:
        issue.ClosingStatus = closing_status
    issue.ClosureRequestedAt = None
    issue.ClosureRequestedBy = None
    # 评分管控: 快照该检查项当时的最新评分 (整改前评分), 必经步骤不可绕过
    snapshot_score_at_closure(db, issue)


def reopen_issue_and_reset_scores(db: Session, issue: Issue) -> None:
    """重开已关闭问题 (清零重置法)

    状态回到 in_progress, 评分管控三字段 (ScoreAtClosure / ScoreAfterUpdate /
    ScoreUpdatedAt) 全部清空, 关闭申请与验证字段同步清零。
    审计追溯依赖调用方写入的评论历史 (含重开原因)。
    """
    issue.Status = "in_progress"
    issue.ClosedAt = None
    issue.ScoreAtClosure = None
    issue.ScoreAfterUpdate = None
    issue.ScoreUpdatedAt = None
    issue.ClosureRequestedAt = None
    issue.ClosureRequestedBy = None
    issue.VerifiedBy = None
    issue.VerifiedAt = None


def snapshot_score_at_closure(db: Session, issue: Issue) -> None:
    """问题批准关闭时, 快照检查项最新评分 (整改前评分)

    取该问题 (PlanId + PhaseReviewItemId) 下最新一条已提交/已确认的评分记录;
    无评分记录时 ScoreAtClosure 保持为空 (不设置默认值)。
    """
    if not (issue.PlanId and issue.PhaseReviewItemId):
        issue.ScoreAtClosure = None
        return
    review = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.PlanId == issue.PlanId,
            ReviewRecord.PhaseReviewItemId == issue.PhaseReviewItemId,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
        )
        .order_by(ReviewRecord.SubmittedAt.desc(), ReviewRecord.Id.desc())
        .first()
    )
    issue.ScoreAtClosure = float(review.Score) if review and review.Score is not None else None


def backfill_score_after_update(db: Session, plan_id: str | None, phase_review_item_id: int | None) -> int:
    """检查项重新评分后, 回写关联已关闭问题的整改后评分

    匹配: 同 (PlanId, PhaseReviewItemId), 状态 closed
    回填策略: 覆盖式 (始终取最新评分) — 已回填过的也无条件更新为当前最新评分,
    ScoreUpdatedAt 同步刷新, 保证评分修正不被静默吞掉。

    同时补全 ScoreAtClosure (整改前评分):
    若关闭时未快照到评分 (关闭早于首次评分), 取该检查项 "最新一条之前的" 评分记录
    作为整改前评分 (仅在为空时补全, 不覆盖已有快照)。

    并发保护: 行锁 (with_for_update), 与 approve_closure 锁粒度一致,
    防止评分回填与关闭审批并发时序错位。

    Returns:
        回写的问题条数
    """
    if not (plan_id and phase_review_item_id):
        return 0
    # 该检查项当前最新评分 (整改后评分的来源)
    latest = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.PlanId == plan_id,
            ReviewRecord.PhaseReviewItemId == phase_review_item_id,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
        )
        .order_by(ReviewRecord.SubmittedAt.desc(), ReviewRecord.Id.desc())
        .first()
    )
    if not latest or latest.Score is None:
        return 0
    # 整改前评分: 排除最新 (整改后) 评分, 取最近一条
    prev = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.PlanId == plan_id,
            ReviewRecord.PhaseReviewItemId == phase_review_item_id,
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
            ReviewRecord.Id != latest.Id,
        )
        .order_by(ReviewRecord.SubmittedAt.desc(), ReviewRecord.Id.desc())
        .first()
    )
    prev_score = float(prev.Score) if prev and prev.Score is not None else None
    now = now_cst()
    closed_issues = (
        db.query(Issue)
        .filter(
            Issue.PlanId == plan_id,
            Issue.PhaseReviewItemId == phase_review_item_id,
            Issue.Status == "closed",
            Issue.IsDeleted == False,  # noqa: E712
        )
        # 行锁: 防止与关闭审批并发时序错位 (统一并发保护)
        .with_for_update()
        .all()
    )
    for issue in closed_issues:
        issue.ScoreAfterUpdate = float(latest.Score)
        issue.ScoreUpdatedAt = now
        # 补全整改前评分: 关闭时未快照到, 但该检查项有更早的评分记录
        if issue.ScoreAtClosure is None and prev_score is not None:
            issue.ScoreAtClosure = prev_score
    if closed_issues:
        logger.info(
            "评分管控: 检查项 {} (Plan {}) 重新评分 {}, 回写 {} 条已关闭问题的整改后评分",
            phase_review_item_id, plan_id, latest.Score, len(closed_issues),
        )
    return len(closed_issues)


def pending_score_update_count(db: Session) -> int:
    """全局"待更新评分"问题数 (已关闭且整改后评分未回写)"""
    return (
        db.query(sqlfunc.count(Issue.Id))
        .filter(
            Issue.Status == "closed",
            Issue.IsDeleted == False,  # noqa: E712
            Issue.PhaseReviewItemId.isnot(None),
            Issue.ScoreAfterUpdate.is_(None),
        )
        .scalar()
        or 0
    )
