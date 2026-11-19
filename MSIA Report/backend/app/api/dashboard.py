"""综合看板分析 API

提供 MSIA 审核管理的多维度数据分析:
1. 工厂综合 MSIA 评分 (按工厂汇总所有项目的审核评分平均值)
2. 项目 MSIA 分值 (按项目和责任人维度, 支持下钻)
3. 问题数量与关闭率 (按工厂 x HML 严重程度, 柱形图+折线图组合)
4. 问题超期分析 (按工厂/责任人维度)

数据关联策略:
- ReviewRecord 通过 PlanId 关联 HRDB 获取 projectName 和 location(工厂)
- Issue 通过 OwnerCompany 获取工厂信息
- 超期判断规则统一调用 app.services.issue_overdue:
  1) 已关闭/待审批关闭 → 不逾期
    2) Deadline 为空 → 不逾期
    3) Deadline 次日零点起且未处于豁免状态 → 逾期

下钻接口:
- GET /factory/{plant}/projects  按工厂下钻到项目评分
- GET /plant/{plant}/issues      按工厂下钻到问题清单 (支持状态筛选)
- GET /project/{id}/drilldown    按项目下钻到评审明细 (兼容 ProjectId 和 PlanId)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.issue import Issue
from app.models.project import Project
from app.models.review import ReviewRecord
from app.models.phase_review_item import PhaseReviewItem
from app.models.user import User
from app.services.hrdb_query_service import HrdbQueryService

router = APIRouter(prefix="/api/dashboard", tags=["综合看板"])


# ============ 响应模型 ============

class FactoryScoreItem(BaseModel):
    plant: str
    avg_score: float
    project_count: int
    review_count: int


class ProjectScoreItem(BaseModel):
    project_id: int
    plan_id: Optional[str] = None
    project_name: str
    plant: str
    owner_name: str
    avg_score: float
    review_count: int


class IssueStatItem(BaseModel):
    plant: str
    total: int
    h_count: int
    m_count: int
    l_count: int
    closed: int
    close_rate: float


class OverdueItem(BaseModel):
    dimension: str
    dimension_type: str
    plant: str
    overdue_count: int
    total_open: int


class DashboardSummary(BaseModel):
    total_projects: int
    total_issues: int
    total_closed: int
    total_overdue: int
    avg_score: Optional[float]


class DashboardAnalytics(BaseModel):
    summary: DashboardSummary
    factory_scores: list[FactoryScoreItem]
    project_scores: list[ProjectScoreItem]
    issue_stats: list[IssueStatItem]
    overdue_by_plant: list[OverdueItem]
    overdue_by_owner: list[OverdueItem]


class IssueListItem(BaseModel):
    id: int
    issue_no: str
    title: str
    owner_name: str
    owner_company: Optional[str]
    severity: str
    status: str
    due_date: Optional[str]
    phase_code: Optional[str]
    project_id: Optional[int]
    is_overdue: bool


# ============ 辅助函数 ============

def _norm_score(score) -> float:
    """将评分归一化到 0-100 范围 (兼容 0-1 和 0-100 两种存储)"""
    if score is None:
        return 0.0
    f = float(score)
    if f <= 1.0:
        return round(f * 100, 1)
    return round(f, 1)


def _latest_review_subquery(db: Session, extra_filters=None):
    """子查询: 每个检查项 (PlanId, PhaseReviewItemId) 的最新已提交评审记录 Id

    确保同一检查项的整改前旧评分不参与最终评分计算,
    仅以最新一次 submitted/confirmed 评分为准。
    """
    q = (
        db.query(func.max(ReviewRecord.Id).label("max_id"))
        .filter(
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
            ReviewRecord.PhaseReviewItemId.isnot(None),
        )
        .group_by(ReviewRecord.PlanId, ReviewRecord.PhaseReviewItemId)
    )
    if extra_filters:
        q = q.filter(*extra_filters)
    return q.subquery()


def _get_naive_utc_now() -> datetime:
    """获取当前北京时间 (东八区 naive), 与 SQL Server sysdatetime() 口径一致"""
    from app.utils.time import now_cst

    return now_cst()


def _get_plan_info_map(db: Session, plan_ids: list[str]) -> dict[str, dict]:
    """批量查询 HRDB 获取 planId -> {projectName, ownerName, location, orderId} 映射

    关联链: msia_plan.orderId = orderBasicInfor.orderId
    """
    if not plan_ids:
        return {}
    unique_ids = list({str(pid).strip() for pid in plan_ids if pid})
    if not unique_ids:
        return {}
    try:
        hrdb_service = HrdbQueryService(settings)
        return hrdb_service.query_plan_owner_infos(unique_ids)
    except Exception:
        return {}


# ============ 主分析接口 ============

@router.get("/analytics", response_model=DashboardAnalytics, summary="综合看板分析数据")
def get_dashboard_analytics(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """获取综合看板所需的全部分析数据

    数据关联策略:
    - 工厂评分/项目评分: 通过 ReviewRecord.PlanId 关联 HRDB 获取 projectName 和 location
    - 问题统计: 按 Issue.OwnerCompany 分组
    - 超期分析: 使用统一的 Deadline 逾期判定服务
    """
    now = _get_naive_utc_now()

    # ---- 1. 工厂综合 MSIA 评分 ----
    # 仅取每个检查项的最新评分 (整改前旧评分不参与计算), 通过 PlanId 关联 HRDB 获取工厂信息
    latest_sq = _latest_review_subquery(db)
    review_query = (
        db.query(
            ReviewRecord.PlanId,
            func.avg(ReviewRecord.Score).label("avg_score"),
            func.count(ReviewRecord.Id).label("review_count"),
        )
        .join(latest_sq, ReviewRecord.Id == latest_sq.c.max_id)
        .filter(
            ReviewRecord.PlanId.isnot(None),
        )
        .group_by(ReviewRecord.PlanId)
        .all()
    )

    # 批量查询 HRDB 获取每个 PlanId 的工厂信息
    plan_ids = [str(r.PlanId).strip() for r in review_query if r.PlanId]
    plan_info_map = _get_plan_info_map(db, plan_ids)

    # 按工厂分组汇总 (按评审记录维度加权平均, 与项目明细口径一致)
    factory_map: dict[str, dict] = {}  # {plant: {weighted_sum, review_count, project_ids}}
    for row in review_query:
        plan_id = str(row.PlanId).strip()
        info = plan_info_map.get(plan_id, {})
        plant = info.get("location", "") or info.get("projectName", "") or "未知"
        if plant not in factory_map:
            factory_map[plant] = {"weighted_sum": 0.0, "review_count": 0, "project_ids": set()}
        # 累加加权总分 (项目平均分 * 评审记录数 = 该项目总分和)
        rc = int(row.review_count or 0)
        factory_map[plant]["weighted_sum"] += float(row.avg_score or 0) * rc
        factory_map[plant]["review_count"] += rc
        factory_map[plant]["project_ids"].add(plan_id)

    factory_scores: list[FactoryScoreItem] = []
    for plant, info in factory_map.items():
        project_count = len(info["project_ids"])
        review_count = info["review_count"]
        # 评审记录维度加权平均: 总分和 / 总评审记录数 (与项目明细 avg(Score) 口径一致)
        avg_score = round(info["weighted_sum"] / review_count, 4) if review_count > 0 else 0.0
        factory_scores.append(FactoryScoreItem(
            plant=plant,
            avg_score=avg_score,
            project_count=project_count,
            review_count=review_count,
        ))
    factory_scores.sort(key=lambda x: x.avg_score, reverse=True)

    # ---- 2. 项目 MSIA 分值 (含责任人) ----
    project_scores: list[ProjectScoreItem] = []
    for row in review_query:
        plan_id = str(row.PlanId).strip()
        info = plan_info_map.get(plan_id, {})
        project_name = info.get("projectName", "") or f"PlanID: {plan_id}"
        plant = info.get("location", "") or "未知"
        owner_name = info.get("ownerName", "") or "未分配"
        project_scores.append(ProjectScoreItem(
            project_id=0,  # 没有本地 Project.Id, 用 0 占位 (下钻通过 plan_id 查)
            plan_id=plan_id,  # 通过 PlanId 关联 HRDB 下钻
            project_name=project_name,
            plant=plant,
            owner_name=owner_name,
            avg_score=_norm_score(row.avg_score) if row.avg_score else 0.0,
            review_count=int(row.review_count) or 0,
        ))
    project_scores.sort(key=lambda x: x.avg_score, reverse=True)

    # ---- 3. 问题数量与关闭率 (按工厂 x HML) ----
    issue_query = (
        db.query(
            Issue.OwnerCompany,
            func.count(Issue.Id).label("total"),
            func.sum(case((Issue.Severity == "H", 1), else_=0)).label("h_count"),
            func.sum(case((Issue.Severity == "M", 1), else_=0)).label("m_count"),
            func.sum(case((Issue.Severity == "L", 1), else_=0)).label("l_count"),
            func.sum(case((Issue.Status == "closed", 1), else_=0)).label("closed"),
        )
        .filter(Issue.IsDeleted == False)  # noqa: E712
        .group_by(Issue.OwnerCompany)
        .all()
    )

    issue_stats: list[IssueStatItem] = []
    for row in issue_query:
        plant = row.OwnerCompany or "未知"
        total = int(row.total) or 0
        closed = int(row.closed) or 0
        issue_stats.append(IssueStatItem(
            plant=plant,
            total=total,
            h_count=int(row.h_count) or 0,
            m_count=int(row.m_count) or 0,
            l_count=int(row.l_count) or 0,
            closed=closed,
            close_rate=round(closed / total, 4) if total > 0 else 0.0,
        ))
    issue_stats.sort(key=lambda x: x.total, reverse=True)

    # ---- 4. 问题超期分析 ----
    # 逾期规则 (统一调用 issue_overdue 服务, 参数从数据库 SystemSetting 读取):
    #   1) 已关闭/待审批关闭 → 不逾期
    #   2) Deadline 为空 → 不逾期
    #   3) Deadline 次日零点起且未处于豁免状态 → 逾期
    from app.services.issue_overdue import build_overdue_filter
    overdue_filter = (
        Issue.IsDeleted == False,  # noqa: E712
        *build_overdue_filter(now, db),
    )

    # 按工厂分组
    overdue_plant_query = (
        db.query(
            Issue.OwnerCompany.label("plant"),
            func.count(Issue.Id).label("overdue_count"),
        )
        .filter(*overdue_filter)
        .group_by(Issue.OwnerCompany)
        .all()
    )

    open_by_plant = (
        db.query(
            Issue.OwnerCompany,
            func.count(Issue.Id).label("total_open"),
        )
        .filter(
            Issue.IsDeleted == False,  # noqa: E712
            Issue.Status.notin_(("closed", "pending_verification")),
        )
        .group_by(Issue.OwnerCompany)
        .all()
    )
    open_plant_map = {row.OwnerCompany or "未知": int(row.total_open) for row in open_by_plant}

    overdue_by_plant: list[OverdueItem] = []
    for row in overdue_plant_query:
        plant = row.plant or "未知"
        overdue_by_plant.append(OverdueItem(
            dimension=plant,
            dimension_type="plant",
            plant=plant,
            overdue_count=int(row.overdue_count) or 0,
            total_open=open_plant_map.get(plant, 0),
        ))
    overdue_by_plant.sort(key=lambda x: x.overdue_count, reverse=True)

    # 按责任人分组
    overdue_owner_query = (
        db.query(
            Issue.OwnerName.label("owner"),
            Issue.OwnerCompany.label("plant"),
            func.count(Issue.Id).label("overdue_count"),
        )
        .filter(*overdue_filter)
        .group_by(Issue.OwnerName, Issue.OwnerCompany)
        .all()
    )

    open_by_owner = (
        db.query(
            Issue.OwnerName,
            func.count(Issue.Id).label("total_open"),
        )
        .filter(
            Issue.IsDeleted == False,  # noqa: E712
            Issue.Status.notin_(("closed", "pending_verification")),
            Issue.OwnerName.isnot(None),
        )
        .group_by(Issue.OwnerName)
        .all()
    )
    open_owner_map = {row.OwnerName: int(row.total_open) for row in open_by_owner}

    overdue_by_owner: list[OverdueItem] = []
    for row in overdue_owner_query:
        owner = row.owner or "未知"
        plant = row.plant or "未知"
        overdue_by_owner.append(OverdueItem(
            dimension=owner,
            dimension_type="owner",
            plant=plant,
            overdue_count=int(row.overdue_count) or 0,
            total_open=open_owner_map.get(owner, 0),
        ))
    overdue_by_owner.sort(key=lambda x: x.overdue_count, reverse=True)

    # ---- 5. 汇总 ----
    total_projects = db.query(func.count(Project.Id)).filter(
        Project.IsDeleted == False  # noqa: E712
    ).scalar() or 0
    # 如果本地 Project 表为空, 用 ReviewRecord distinct PlanId 数量
    if total_projects == 0:
        total_projects = db.query(func.count(func.distinct(ReviewRecord.PlanId))).filter(
            ReviewRecord.PlanId.isnot(None)
        ).scalar() or 0

    total_issues = db.query(func.count(Issue.Id)).filter(
        Issue.IsDeleted == False  # noqa: E712
    ).scalar() or 0

    total_closed = db.query(func.count(Issue.Id)).filter(
        Issue.IsDeleted == False,  # noqa: E712
        Issue.Status == "closed",
    ).scalar() or 0

    total_overdue = db.query(func.count(Issue.Id)).filter(*overdue_filter).scalar() or 0

    # 全局平均分: 仅取每个检查项最新评分
    latest_sq2 = _latest_review_subquery(db)
    overall_avg = (
        db.query(func.avg(ReviewRecord.Score))
        .join(latest_sq2, ReviewRecord.Id == latest_sq2.c.max_id)
        .scalar()
    )

    summary = DashboardSummary(
        total_projects=total_projects,
        total_issues=total_issues,
        total_closed=total_closed,
        total_overdue=total_overdue,
        avg_score=_norm_score(overall_avg) if overall_avg else None,
    )

    return DashboardAnalytics(
        summary=summary,
        factory_scores=factory_scores,
        project_scores=project_scores,
        issue_stats=issue_stats,
        overdue_by_plant=overdue_by_plant,
        overdue_by_owner=overdue_by_owner,
    )


# ============ 下钻接口 ============

@router.get("/factory/{plant}/projects", summary="工厂下钻 - 查看该工厂内各项目的 MSIA 评分")
def get_factory_projects(
    plant: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """下钻查看指定工厂内各项目的 MSIA 评分 (通过 PlanId 关联 HRDB)"""
    # 仅取每个检查项最新评分, 按 PlanId 分组
    latest_sq = _latest_review_subquery(db)
    review_query = (
        db.query(
            ReviewRecord.PlanId,
            func.avg(ReviewRecord.Score).label("avg_score"),
            func.count(ReviewRecord.Id).label("review_count"),
        )
        .join(latest_sq, ReviewRecord.Id == latest_sq.c.max_id)
        .filter(
            ReviewRecord.PlanId.isnot(None),
        )
        .group_by(ReviewRecord.PlanId)
        .all()
    )

    # 批量查询 HRDB 获取项目信息
    plan_ids = [str(r.PlanId).strip() for r in review_query if r.PlanId]
    plan_info_map = _get_plan_info_map(db, plan_ids)

    # 按工厂过滤
    results = []
    for row in review_query:
        plan_id = str(row.PlanId).strip()
        info = plan_info_map.get(plan_id, {})
        project_plant = info.get("location", "") or "未知"
        if project_plant != plant:
            continue
        project_name = info.get("projectName", "") or f"PlanID: {plan_id}"
        owner_name = info.get("ownerName", "") or "未分配"
        results.append({
            "project_id": 0,
            "plan_id": plan_id,
            "project_name": project_name,
            "plant": plant,
            "owner_name": owner_name,
            "avg_score": _norm_score(row.avg_score) if row.avg_score else 0.0,
            "review_count": int(row.review_count) or 0,
        })
    results.sort(key=lambda x: x["avg_score"], reverse=True)
    return {"plant": plant, "projects": results}


@router.get("/plant/{plant}/issues", summary="工厂下钻 - 查看该工厂的问题清单")
def get_plant_issues(
    plant: str,
    status_filter: Optional[str] = Query(None, alias="status", description="筛选: all/closed/open/overdue"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """下钻查看指定工厂的问题清单, 支持状态筛选

    返回字段含 project_name, 通过以下顺序解析:
    1. Issue.ProjectId -> Project.Name (本地表, 兼容旧数据)
    2. Issue.PlanId -> HRDB 批量查询 projectName (主路径)
    3. 都查不到 -> "未关联项目"
    """
    now = _get_naive_utc_now()
    from app.services.issue_overdue import build_overdue_filter, is_issue_overdue
    query = (
        db.query(Issue, Project.Name.label("project_name"))
        .outerjoin(Project, Issue.ProjectId == Project.Id)
        .filter(
            Issue.IsDeleted == False,  # noqa: E712
            Issue.OwnerCompany == plant,
        )
    )

    if status_filter == "closed":
        query = query.filter(Issue.Status == "closed")
    elif status_filter == "open":
        query = query.filter(Issue.Status != "closed")
    elif status_filter == "overdue":
        query = query.filter(*build_overdue_filter(now, db))

    rows = query.order_by(Issue.CreatedAt.desc()).all()

    # 收集所有 PlanId, 批量查 HRDB 获取项目名
    plan_ids_to_query = [
        str(iss.PlanId).strip()
        for iss, _ in rows
        if iss.PlanId and not iss.ProjectId  # 已有 Project.Name 的跳过
    ]
    plan_id_to_name: dict[str, str] = {}
    if plan_ids_to_query:
        try:
            hrdb_service = HrdbQueryService(settings)
            plan_id_to_name = hrdb_service.query_plan_project_names(plan_ids_to_query)
        except Exception:
            plan_id_to_name = {}

    return {
        "plant": plant,
        "total": len(rows),
        "issues": [
            {
                "id": iss.Id,
                "issue_no": iss.IssueNo,
                "title": iss.Title,
                "owner_name": iss.OwnerName or "",
                "owner_company": iss.OwnerCompany,
                "severity": iss.Severity or "M",
                "status": iss.Status or "open",
                "due_date": iss.Deadline.strftime("%Y-%m-%d") if iss.Deadline else None,
                "phase_code": iss.PhaseCode,
                "project_id": iss.ProjectId,
                "project_name": _resolve_project_name(
                    iss, proj_name, plan_id_to_name
                ),
                "is_overdue": is_issue_overdue(iss, now, db),
            }
            for iss, proj_name in rows
        ],
    }


def _resolve_project_name(
    issue: Issue,
    local_proj_name: Optional[str],
    plan_id_to_name: dict[str, str],
) -> str:
    """解析问题所属项目名, 优先级:
    1. 本地 Project.Name (兼容旧数据)
    2. HRDB 通过 PlanId 查询的 projectName (主路径)
    3. "未关联项目" 兜底
    """
    if local_proj_name:
        return local_proj_name
    if issue.PlanId:
        name = plan_id_to_name.get(str(issue.PlanId).strip())
        if name:
            return name
    return "未关联项目"


@router.get("/project/{project_id}/drilldown", summary="项目下钻数据 - 查看该项目的评审明细")
def get_project_drilldown(
    project_id: int,
    plan_id: Optional[str] = Query(None, description="MSIA 计划 ID (当 project_id=0 时通过 plan_id 查询)"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """下钻查看指定项目的评审明细: 各阶段评分、各检查项评分

    支持两种查询方式:
    1. project_id > 0: 通过本地 Project.Id 查询 (兼容旧数据)
    2. project_id=0 + plan_id: 通过 ReviewRecord.PlanId 查询 (主路径)
    """
    project = None
    if project_id > 0:
        project = db.query(Project).filter(
            Project.Id == project_id, Project.IsDeleted == False  # noqa: E712
        ).first()

    # 如果有 plan_id, 优先使用 plan_id 查询评审记录
    effective_plan_id = plan_id
    project_name = ""
    plant = ""

    if project:
        project_name = project.Name
        plant = project.PlantMe or "未知"
    elif effective_plan_id:
        # 通过 HRDB 查询项目名和工厂
        plan_info_map = _get_plan_info_map(db, [effective_plan_id])
        info = plan_info_map.get(effective_plan_id, {})
        project_name = info.get("projectName", "") or f"PlanID: {effective_plan_id}"
        plant = info.get("location", "") or "未知"

    # 项目不存在且没有 plan_id 时返回空结构
    if not project and not effective_plan_id:
        return {
            "project": {"id": project_id, "name": "", "plant": ""},
            "phase_scores": [],
            "item_scores": [],
            "issue_summary": {"total": 0, "closed": 0, "overdue": 0},
        }

    now = _get_naive_utc_now()

    # 构建查询条件
    if effective_plan_id:
        review_filter = (ReviewRecord.PlanId == effective_plan_id, ReviewRecord.Score.isnot(None))
        issue_filter = (Issue.PlanId == effective_plan_id, Issue.IsDeleted == False)  # noqa: E712
    else:
        review_filter = (ReviewRecord.ProjectId == project_id, ReviewRecord.Score.isnot(None))
        issue_filter = (Issue.ProjectId == project_id, Issue.IsDeleted == False)  # noqa: E712

    # 各阶段评分 (仅取每个检查项最新评分, 整改前旧评分不参与计算)
    if effective_plan_id:
        latest_sq = _latest_review_subquery(db, [ReviewRecord.PlanId == effective_plan_id])
        phase_scores = (
            db.query(
                ReviewRecord.PhaseCode,
                func.avg(ReviewRecord.Score).label("avg_score"),
                func.count(ReviewRecord.Id).label("count"),
            )
            .join(latest_sq, ReviewRecord.Id == latest_sq.c.max_id)
            .group_by(ReviewRecord.PhaseCode)
            .all()
        )
        # 各检查项评分明细 (仅取每个检查项最新评分)
        item_scores = (
            db.query(
                ReviewRecord.ItemNo,
                ReviewRecord.PhaseCode,
                ReviewRecord.Score,
                ReviewRecord.ResultText,
                ReviewRecord.Status,
                ReviewRecord.Comments,
            )
            .join(latest_sq, ReviewRecord.Id == latest_sq.c.max_id)
            .order_by(ReviewRecord.PhaseCode, ReviewRecord.ItemNo)
            .all()
        )
    else:
        phase_scores = (
            db.query(
                ReviewRecord.PhaseCode,
                func.avg(ReviewRecord.Score).label("avg_score"),
                func.count(ReviewRecord.Id).label("count"),
            )
            .filter(*review_filter)
            .group_by(ReviewRecord.PhaseCode)
            .all()
        )
        item_scores = (
            db.query(
                ReviewRecord.ItemNo,
                ReviewRecord.PhaseCode,
                ReviewRecord.Score,
                ReviewRecord.ResultText,
                ReviewRecord.Status,
                ReviewRecord.Comments,
            )
            .filter(*review_filter)
            .order_by(ReviewRecord.PhaseCode, ReviewRecord.ItemNo)
            .all()
        )

    # 该项目的问题统计
    from app.services.issue_overdue import build_overdue_condition
    overdue_condition = build_overdue_condition(now, db)
    issue_stats_row = (
        db.query(
            func.count(Issue.Id).label("total"),
            func.sum(case((Issue.Status == "closed", 1), else_=0)).label("closed"),
            func.sum(case((overdue_condition, 1), else_=0)).label("overdue"),
        )
        .filter(*issue_filter)
        .first()
    )

    return {
        "project": {
            "id": project_id,
            "name": project_name,
            "plant": plant,
        },
        "phase_scores": [
            {
                "phase_code": r.PhaseCode or "",
                "avg_score": _norm_score(r.avg_score) if r.avg_score else 0.0,
                "count": int(r.count) or 0,
            }
            for r in phase_scores
        ],
        "item_scores": [
            {
                "item_no": r.ItemNo or "",
                "phase_code": r.PhaseCode or "",
                "score": _norm_score(r.Score) if r.Score else 0.0,
                "result_text": r.ResultText or "",
                "status": r.Status or "",
                "comments": r.Comments or "",
            }
            for r in item_scores
        ],
        "issue_summary": {
            "total": int(issue_stats_row.total) if issue_stats_row and issue_stats_row.total else 0,
            "closed": int(issue_stats_row.closed) if issue_stats_row and issue_stats_row.closed else 0,
            "overdue": int(issue_stats_row.overdue) if issue_stats_row and issue_stats_row.overdue else 0,
        },
    }


@router.get("/score-improvement", summary="评分改进分析 - 整改前后评分差异")
def get_score_improvement(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """查询所有检查项的首次评分 (整改前) 和最新评分 (整改后) 的差异

    仅显示有多条评分记录 (即经历过重新评分) 的检查项,
    便于管理员/审核员分析整改效果。
    """
    from collections import defaultdict

    # 查所有 submitted/confirmed 的评分记录, 按检查项分组
    records = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.Score.isnot(None),
            ReviewRecord.Status.in_(["submitted", "confirmed"]),
            ReviewRecord.PlanId.isnot(None),
            ReviewRecord.PhaseReviewItemId.isnot(None),
        )
        .order_by(ReviewRecord.PlanId, ReviewRecord.PhaseReviewItemId, ReviewRecord.Id)
        .all()
    )

    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        groups[(r.PlanId, r.PhaseReviewItemId)].append(r)

    # 批量查项目名称 (HRDB)
    plan_ids = list({str(k[0]).strip() for k in groups.keys()})
    plan_info_map = _get_plan_info_map(db, plan_ids)

    # 批量查检查项名称
    item_ids = list({k[1] for k in groups.keys()})
    items_map = {}
    if item_ids:
        items = db.query(PhaseReviewItem).filter(PhaseReviewItem.Id.in_(item_ids)).all()
        items_map = {it.Id: it for it in items}

    results = []
    for (plan_id, item_id), recs in groups.items():
        if len(recs) < 2:
            continue  # 仅一条评分, 无整改差异
        first = recs[0]
        latest = recs[-1]
        info = plan_info_map.get(str(plan_id).strip(), {})
        item = items_map.get(item_id)
        first_score = _norm_score(first.Score) if first.Score else 0.0
        latest_score = _norm_score(latest.Score) if latest.Score else 0.0
        results.append({
            "plan_id": str(plan_id),
            "project_name": info.get("projectName", "") or f"PlanID: {plan_id}",
            "plant": info.get("location", "") or "未知",
            "phase_code": latest.PhaseCode or "",
            "item_id": item_id,
            "item_name": item.ItemName if item else f"#{item_id}",
            "item_no": latest.ItemNo or "",
            "first_score": first_score,
            "latest_score": latest_score,
            "improvement": round(latest_score - first_score, 1),
            "review_count": len(recs),
        })

    results.sort(key=lambda x: x["improvement"], reverse=True)
    return {"items": results, "total": len(results)}


@router.get("/score-improvement/history", summary="评分改进分析 - 检查项评审历史明细")
def get_score_improvement_history(
    plan_id: str = Query(..., description="MSIA 计划 ID"),
    item_id: int = Query(..., description="阶段评审检查项 ID (PhaseReviewItemId)"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """查询指定项目下某检查项的全部评审记录 (整改前后明细)

    用于评分改进分析列表的行点击下钻:
    展示每次评分的时间、评分人、分值、结果与评审意见,
    让用户清楚看到"首次评分"与"整改后评分"的来源。
    """
    # 查询该 (plan_id, item_id) 的所有评审记录 (含草稿, 按时间正序)
    records = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.PlanId == str(plan_id),
            ReviewRecord.PhaseReviewItemId == item_id,
        )
        .order_by(ReviewRecord.Id.asc())
        .all()
    )
    if not records:
        raise HTTPException(status_code=404, detail="未找到该检查项的评审记录")

    # 检查项信息
    item = db.query(PhaseReviewItem).filter(PhaseReviewItem.Id == item_id).first()

    # 项目信息 (HRDB)
    info_map = _get_plan_info_map(db, [str(plan_id).strip()])
    info = info_map.get(str(plan_id).strip(), {})

    # 评审人姓名映射
    reviewer_ids = list({r.ReviewerId for r in records})
    reviewers = db.query(User).filter(User.Id.in_(reviewer_ids)).all()
    reviewer_map = {u.Id: (u.DisplayName or u.Username or f"#{u.Id}") for u in reviewers}

    def _fmt_dt(dt):
        return dt.strftime("%Y-%m-%d %H:%M") if dt else None

    history = []
    for idx, r in enumerate(records):
        score = _norm_score(r.Score) if r.Score is not None else None
        history.append({
            "seq": idx + 1,
            "review_id": r.Id,
            "score": score,
            "result_text": r.ResultText or "",
            "comments": r.Comments or "",
            "status": r.Status,
            "reviewer_name": reviewer_map.get(r.ReviewerId, f"#{r.ReviewerId}"),
            "submitted_at": _fmt_dt(r.SubmittedAt),
            "created_at": _fmt_dt(r.CreatedAt),
        })

    # 首次/最新评分取自已提交的记录 (与列表口径一致)
    submitted = [h for h in history if h["score"] is not None]
    first_score = submitted[0]["score"] if submitted else None
    latest_score = submitted[-1]["score"] if submitted else None

    return {
        "plan_id": str(plan_id),
        "project_name": info.get("projectName", "") or f"PlanID: {plan_id}",
        "plant": info.get("location", "") or "未知",
        "phase_code": records[-1].PhaseCode or (item.PhaseCode if item else ""),
        "item_id": item_id,
        "item_name": item.ItemName if item else f"#{item_id}",
        "item_no": records[-1].ItemNo or "",
        "records": history,
        "first_score": first_score,
        "latest_score": latest_score,
        "improvement": (
            round(latest_score - first_score, 1)
            if first_score is not None and latest_score is not None
            else None
        ),
    }
