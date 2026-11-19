"""问题跟踪路由 - 简单的问题闭环管理

功能:
- 列表/详情/创建/更新/删除
- 状态变更 + 验证 (lead_reviewer/admin)
- 评论历史 (IssueComment): 记录所有处理过程、整改说明、验证意见
- 自动生成 IssueNo (格式: ISS-{YYYYMMDD}-{NNN})
- 创建时自动从 HRDB 关联责任人 userId + 所属公司 (location)
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.attachment import Attachment
from app.models.issue import Issue
from app.models.issue_comment import IssueComment
from app.models.phase_review_item import PhaseReviewItem
from app.models.user import User
from app.schemas.common import PageResponse
from app.schemas.issue import (
    AttachmentOut,
    IssueCommentCreate,
    IssueCommentOut,
    IssueCreate,
    IssueOut,
    IssueReopen,
    IssueStatsOut,
    IssueStatusUpdate,
    IssueUpdate,
)
from app.services.hrdb_query_service import HrdbQueryService
from app.services.issue_project_service import attach_project_names
from app.services.score_control_service import (
    close_issue_with_snapshot,
    reopen_issue_and_reset_scores,
)
from app.utils.pagination import paginate
from app.utils.time import now_cst

router = APIRouter(prefix="/api/issues", tags=["问题"])


def _get_archived_plan_ids() -> list[str]:
    """查询归档项目 planId 集合 (问题管理模块排除归档项目的问题)

    归档判定与项目存档模块一致: MSIA3/4/5 实际日期全部已维护。
    HRDB 查询失败时返回空列表 (降级为不过滤, 不阻断问题管理主流程)。
    """
    try:
        return HrdbQueryService(settings).query_archived_plan_ids()
    except Exception as exc:
        logger.warning("查询归档项目失败, 问题管理本次不排除归档数据: {}", exc)
        return []


def _exclude_archived(query):
    """在问题查询上追加"排除归档项目"过滤 (未关联项目的记录不受影响)

    注意: SQL 三值逻辑下 NULL NOT IN (...) 结果为 NULL,
    需显式放行 PlanId 为 NULL 的未关联项目问题。
    """
    archived = _get_archived_plan_ids()
    if archived:
        return query.filter(
            or_(Issue.PlanId.is_(None), ~Issue.PlanId.in_(archived))
        )
    return query


def _gen_issue_no(db: Session) -> str:
    """生成 IssueNo: ISS-YYYYMMDD-NNN (按当日序号递增)"""
    today = now_cst().strftime("%Y%m%d")
    prefix = f"ISS-{today}-"
    # 查询当日最大序号
    last = (
        db.query(Issue)
        .filter(Issue.IssueNo.like(f"{prefix}%"))
        .order_by(Issue.IssueNo.desc())
        .first()
    )
    seq = 1
    if last and last.IssueNo:
        try:
            seq = int(last.IssueNo[-3:]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:03d}"


def _add_comment(
    db: Session,
    issue: Issue,
    current: User,
    content: str,
    action: str = "comment",
    from_status: str | None = None,
    to_status: str | None = None,
) -> IssueComment:
    """记录一条问题评论/操作历史"""
    comment = IssueComment(
        IssueId=issue.Id,
        AuthorUserId=current.Id,
        AuthorName=current.DisplayName or current.Username,
        Action=action,
        Content=content,
        FromStatus=from_status,
        ToStatus=to_status,
    )
    db.add(comment)
    return comment


def _resolve_issue_owner(
    db: Session,
    plan_id: str | None,
    owner_name: str | None,
) -> tuple[int | None, str | None, str | None, str | None]:
    """根据 PlanId 查询 HRDB, 自动填充 OwnerUserId / OwnerName / OwnerCompany / OwnerUserName

    Args:
        db: 主数据库会话 (用于查询本地 User 表)
        plan_id: MSIA 计划 ID
        owner_name: 用户传入的责任人姓名 (可覆盖)

    Returns:
        (owner_user_id, owner_name_resolved, owner_company, owner_user_name)
        - owner_user_id: 本地 User.Id (通过 HRDB userName_in_charge 匹配 Username)
        - owner_name_resolved: 责任人中文姓名
        - owner_company: 所属公司 (HRDB location)
        - owner_user_name: HRDB userName_in_charge (英文账号, 用于权限匹配)
    """
    if not plan_id:
        return None, owner_name, None, None

    try:
        service = HrdbQueryService(settings)
        owner_info = service.query_plan_owner_info(plan_id)
    except Exception:
        owner_info = None

    if not owner_info:
        return None, owner_name, None, None

    # 所属公司 = HRDB 工单的 location 字段
    owner_company = owner_info.get("location") or None

    # 责任人姓名: 优先使用用户传入, 否则使用 HRDB 解析的中文名
    resolved_name = owner_name or owner_info.get("ownerName")

    # 关联本地用户: 通过 HRDB 的 userName_in_charge 匹配 Username
    owner_user_id = None
    user_name_in_charge = owner_info.get("userName_in_charge")
    if user_name_in_charge:
        user = db.query(User).filter(User.Username == user_name_in_charge).first()
        if user:
            owner_user_id = user.Id

    return owner_user_id, resolved_name, owner_company, user_name_in_charge


def _list_issue_attachments(db: Session, issue_id: int) -> list[Attachment]:
    """查询问题审核证据附件列表 (审核员登记问题时上传)"""
    return (
        db.query(Attachment)
        .filter(Attachment.OwnerType == "issue", Attachment.OwnerId == issue_id)
        .order_by(Attachment.CreatedAt.asc())
        .all()
    )


def _list_issue_closure_attachments(db: Session, issue_id: int) -> list[Attachment]:
    """查询问题关闭证据附件列表 (被审核人申请关闭时上传)"""
    return (
        db.query(Attachment)
        .filter(Attachment.OwnerType == "issue_closure", Attachment.OwnerId == issue_id)
        .order_by(Attachment.CreatedAt.asc())
        .all()
    )


@router.get("/filter-options", summary="问题筛选选项 (项目 + 责任人)")
def list_issue_filter_options(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回问题列表筛选用的项目和责任人去重选项

    关联 HRDB 获取真实项目名称 (projectName) 和负责人 (name_in_charge 解析中文名):
    - 项目选项: 从 Issue 表 distinct PlanId, 批量查询 HRDB 获取 projectName
      value = PlanId (用于过滤), label = "projectName (PlanId)" 便于识别
    - 责任人选项: 从 HRDB 获取负责人中文名, 去重排序
      value = ownerName (用于过滤), label = ownerName
    """
    # 1. 从 Issue 表获取所有 distinct PlanId (排除归档项目, 与问题列表口径一致)
    plan_rows = (
        db.query(Issue.PlanId)
        .filter(
            Issue.IsDeleted == False,  # noqa: E712
            Issue.PlanId.isnot(None),
            Issue.PlanId != "",
        )
        .distinct()
        .all()
    )
    plan_ids = [str(pid) for (pid,) in plan_rows if pid]
    archived_ids = set(_get_archived_plan_ids())
    if archived_ids:
        plan_ids = [pid for pid in plan_ids if pid not in archived_ids]

    # 2. 批量查询 HRDB 获取每个 planId 的 projectName 和 ownerName
    hrdb_service = HrdbQueryService(settings)
    plan_info_map = hrdb_service.query_plan_owner_infos(plan_ids)

    # 3. 构建项目选项 (去重 projectName, 保留 planId 关联)
    # 同一个 projectName 可能对应多个 planId, 但筛选时按 planId 过滤
    project_options = []
    seen_project_names = set()
    for pid in sorted(plan_ids):
        info = plan_info_map.get(pid)
        project_name = info.get("projectName", "") if info else ""
        if project_name and project_name not in seen_project_names:
            seen_project_names.add(project_name)
            project_options.append({
                "value": pid,
                "label": f"{project_name} (PlanID: {pid})",
                "projectName": project_name,
            })
        elif not project_name:
            # HRDB 未找到, 仅显示 PlanId
            project_options.append({
                "value": pid,
                "label": f"(PlanID: {pid})",
                "projectName": "",
            })

    # 4. 构建负责人选项 (从 HRDB 获取的 ownerName 去重排序)
    owner_names = set()
    for info in plan_info_map.values():
        owner = info.get("ownerName", "")
        if owner:
            owner_names.add(owner)
    owner_options = [
        {"value": name, "label": name}
        for name in sorted(owner_names)
    ]

    # 5. 项目 ↔ 责任人 映射 (供前端级联筛选: 选项目后联动责任人选项, 反之亦然)
    project_owner_map: dict[str, list[str]] = {}
    for pid in plan_ids:
        info = plan_info_map.get(pid)
        owner = (info.get("ownerName", "") if info else "").strip()
        if owner:
            project_owner_map.setdefault(pid, []).append(owner)

    return {
        "projects": project_options,
        "owners": owner_options,
        "project_owner_map": project_owner_map,
    }


@router.get("", response_model=PageResponse[IssueOut], summary="问题列表")
def list_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    project_id: int | None = Query(None),
    phase_review_item_id: int | None = Query(None, description="按阶段评审检查项 ID 过滤"),
    plan_id: str | None = Query(None, description="按 MSIA 计划 ID 过滤 (单选, 兼容旧参数)"),
    plan_ids: str | None = Query(None, description="按 MSIA 计划 ID 多选过滤 (英文逗号分隔)"),
    phase_code: str | None = Query(None, description="按阶段代码过滤 (单选, 兼容旧参数)"),
    phase_codes: str | None = Query(None, description="按阶段代码多选过滤 (英文逗号分隔, MSIA1~5)"),
    status_filter: str | None = Query(None, alias="status"),
    priority: str | None = Query(None),
    severity: str | None = Query(None, description="按严重等级过滤 H/M/L"),
    keyword: str | None = Query(None, description="按标题模糊搜索"),
    owner_name: str | None = Query(None, description="按责任人姓名过滤 (模糊匹配, 单选兼容)"),
    owner_names: str | None = Query(None, description="按责任人姓名多选过滤 (英文逗号分隔)"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(Issue).filter(Issue.IsDeleted == False)  # noqa: E712
    if project_id:
        query = query.filter(Issue.ProjectId == project_id)
    if phase_review_item_id:
        query = query.filter(Issue.PhaseReviewItemId == phase_review_item_id)
    # 项目过滤: plan_ids 多选优先, 否则回退到 plan_id 单选
    has_plan_filter = False
    if plan_ids:
        pid_list = [s.strip() for s in plan_ids.split(",") if s.strip()]
        if pid_list:
            query = query.filter(Issue.PlanId.in_(pid_list))
            has_plan_filter = True
    elif plan_id:
        query = query.filter(Issue.PlanId == plan_id)
        has_plan_filter = True
    # 排除归档项目的问题 (在"项目存档"模块统一查看);
    # 显式指定项目查询时不排除 (项目存档详情按 plan_id 查询该项目全部问题)
    if not has_plan_filter:
        query = _exclude_archived(query)
    # 阶段过滤: phase_codes 多选优先, 否则回退到 phase_code 单选
    if phase_codes:
        pc_list = [s.strip() for s in phase_codes.split(",") if s.strip()]
        if pc_list:
            query = query.filter(Issue.PhaseCode.in_(pc_list))
    elif phase_code:
        query = query.filter(Issue.PhaseCode == phase_code)
    if status_filter:
        if status_filter == "overdue":
            # 逾期筛选: 统一调用 issue_overdue 服务, 与看板统计/升级扫描口径一致
            from app.services.issue_overdue import build_overdue_filter

            query = query.filter(*build_overdue_filter(db=db))
        else:
            query = query.filter(Issue.Status == status_filter)
    if priority:
        query = query.filter(Issue.Priority == priority)
    if severity:
        query = query.filter(Issue.Severity == severity)
    if keyword:
        query = query.filter(Issue.Title.like(f"%{keyword}%"))
    # 责任人过滤: owner_names 多选优先, 否则回退到 owner_name 模糊匹配
    if owner_names:
        name_list = [s.strip() for s in owner_names.split(",") if s.strip()]
        if name_list:
            query = query.filter(Issue.OwnerName.in_(name_list))
    elif owner_name:
        query = query.filter(Issue.OwnerName.like(f"%{owner_name}%"))
    query = query.order_by(Issue.Id.desc())
    page_data = paginate(query, page, page_size, schema=IssueOut)
    # 为每条问题注入审核证据 + 关闭证据附件列表
    if page_data.items:
        issue_ids = [it.Id for it in page_data.items]
        att_rows = (
            db.query(Attachment)
            .filter(
                Attachment.OwnerType.in_(["issue", "issue_closure"]),
                Attachment.OwnerId.in_(issue_ids),
            )
            .order_by(Attachment.CreatedAt.asc())
            .all()
        )
        evidence_map: dict[int, list[AttachmentOut]] = {}
        closure_map: dict[int, list[AttachmentOut]] = {}
        for att in att_rows:
            out = AttachmentOut.model_validate(att)
            if att.OwnerType == "issue_closure":
                closure_map.setdefault(att.OwnerId, []).append(out)
            else:
                evidence_map.setdefault(att.OwnerId, []).append(out)
        # 注入项目名称 (HRDB) 与检查项名称 (评分条款定位)
        attach_project_names(db, page_data.items)
        prids = [it.PhaseReviewItemId for it in page_data.items if it.PhaseReviewItemId]
        item_name_map: dict[int, str] = {}
        if prids:
            rows = db.query(PhaseReviewItem.Id, PhaseReviewItem.ItemName).filter(
                PhaseReviewItem.Id.in_(prids)
            ).all()
            item_name_map = {rid: name for rid, name in rows}
        for it in page_data.items:
            # Pydantic v2 默认允许字段赋值
            it.Evidence = evidence_map.get(it.Id, [])
            it.ClosureEvidence = closure_map.get(it.Id, [])
            it.ItemName = item_name_map.get(it.PhaseReviewItemId, "") if it.PhaseReviewItemId else ""
    return page_data


@router.get(
    "/stats/summary",
    response_model=IssueStatsOut,
    summary="问题统计概览 (闭环管理仪表盘)",
)
def get_issue_stats(
    plan_id: str | None = Query(None, description="按 MSIA 计划 ID 过滤 (单选, 兼容旧参数)"),
    plan_ids: str | None = Query(None, description="按 MSIA 计划 ID 多选过滤 (英文逗号分隔)"),
    phase_code: str | None = Query(None, description="按阶段代码过滤 (单选, 兼容旧参数)"),
    phase_codes: str | None = Query(None, description="按阶段代码多选过滤 (英文逗号分隔)"),
    owner_name: str | None = Query(None, description="按责任人姓名过滤 (单选兼容)"),
    owner_names: str | None = Query(None, description="按责任人姓名多选过滤 (英文逗号分隔)"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回各状态、优先级、逾期统计 (用于问题闭环管理仪表盘)

    逾期判定规则统一调用 app.services.issue_overdue:
    1) 已关闭/待审批关闭 → 不逾期
    2) Deadline 为空 → 不逾期
    3) Deadline 次日零点起且未处于豁免状态 → 逾期
    """
    base = db.query(Issue).filter(Issue.IsDeleted == False)  # noqa: E712
    # 项目过滤: plan_ids 多选优先, 否则回退到 plan_id 单选
    has_plan_filter = False
    if plan_ids:
        pid_list = [s.strip() for s in plan_ids.split(",") if s.strip()]
        if pid_list:
            base = base.filter(Issue.PlanId.in_(pid_list))
            has_plan_filter = True
    elif plan_id:
        base = base.filter(Issue.PlanId == plan_id)
        has_plan_filter = True
    # 排除归档项目的问题 (与问题列表口径一致);
    # 显式指定项目查询时不排除 (项目存档详情按 plan_id 统计该项目全部问题)
    if not has_plan_filter:
        base = _exclude_archived(base)
    # 阶段过滤: phase_codes 多选优先
    if phase_codes:
        pc_list = [s.strip() for s in phase_codes.split(",") if s.strip()]
        if pc_list:
            base = base.filter(Issue.PhaseCode.in_(pc_list))
    elif phase_code:
        base = base.filter(Issue.PhaseCode == phase_code)
    # 责任人过滤: owner_names 多选优先
    if owner_names:
        name_list = [s.strip() for s in owner_names.split(",") if s.strip()]
        if name_list:
            base = base.filter(Issue.OwnerName.in_(name_list))
    elif owner_name:
        base = base.filter(Issue.OwnerName.like(f"%{owner_name}%"))

    total = base.count()
    open_count = base.filter(Issue.Status == "open").count()
    in_progress_count = base.filter(Issue.Status == "in_progress").count()
    pending_count = base.filter(Issue.Status == "pending_verification").count()
    closed_count = base.filter(Issue.Status == "closed").count()
    high_priority_count = base.filter(Issue.Priority == "high").count()

    # 逾期判定: 统一调用 issue_overdue 服务 (参数从数据库读取)
    # 1) 已关闭/待审批关闭 → 不逾期
    # 2) Deadline 为空 → 不逾期
    # 3) Deadline 次日零点起且未处于豁免状态 → 逾期
    from app.services.issue_overdue import build_overdue_filter, get_naive_utc_now
    overdue_count = (
        base.filter(*build_overdue_filter(get_naive_utc_now(), db))
        .count()
    )

    return IssueStatsOut(
        total=total,
        open_count=open_count,
        in_progress_count=in_progress_count,
        pending_verification_count=pending_count,
        closed_count=closed_count,
        overdue_count=overdue_count,
        high_priority_count=high_priority_count,
    )


@router.get("/{issue_id}", response_model=IssueOut, summary="问题详情")
def get_issue(issue_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """返回问题详情 (含审核证据 + 关闭证据附件列表)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    # 注入审核证据 + 关闭证据附件
    attachments = _list_issue_attachments(db, issue.Id)
    closure_attachments = _list_issue_closure_attachments(db, issue.Id)
    # 注入项目名称 + 检查项名称
    attach_project_names(db, [issue])
    issue_out = IssueOut.model_validate(issue)
    issue_out.Evidence = [AttachmentOut.model_validate(a) for a in attachments]
    issue_out.ClosureEvidence = [AttachmentOut.model_validate(a) for a in closure_attachments]
    if issue.PhaseReviewItemId:
        pr = db.query(PhaseReviewItem.ItemName).filter(PhaseReviewItem.Id == issue.PhaseReviewItemId).first()
        issue_out.ItemName = pr[0] if pr else ""
    else:
        issue_out.ItemName = ""
    return issue_out


@router.post(
    "",
    response_model=IssueOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建问题",
)
def create_issue(payload: IssueCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """创建问题: IssueNo 留空时自动生成; 创建后自动记录一条 assign 评论

    自动填充逻辑:
    - 根据 PlanId 查询 HRDB, 获取 userName_in_charge 对应的本地 User.Id 作为 OwnerUserId
    - 获取 HRDB realName 中括号内中文作为 OwnerName (若用户未传入)
    - 获取 HRDB 工单的 location 字段作为 OwnerCompany (所属公司/工厂)

    权限: 仅审核员 (admin/lead_reviewer/reviewer) 可登记问题, 被审核员不可
    """
    # 权限: 仅审核员 (admin/lead_reviewer/reviewer) 可创建问题, 被审核员不可
    if current.Role not in ("admin", "lead_reviewer", "reviewer"):
        raise HTTPException(status_code=403, detail="被审核人员无权登记问题, 仅审核员可登记")
    data = payload.model_dump(exclude_unset=True)
    if not data.get("IssueNo"):
        data["IssueNo"] = _gen_issue_no(db)

    # 自动填充责任人 userId / 公司 / userName (若 PlanId 存在)
    plan_id = data.get("PlanId")
    user_provided_name = data.get("OwnerName")
    owner_user_id, resolved_name, owner_company, owner_user_name = _resolve_issue_owner(
        db, plan_id, user_provided_name
    )

    if owner_user_id and not data.get("OwnerUserId"):
        data["OwnerUserId"] = owner_user_id
    if resolved_name and not data.get("OwnerName"):
        data["OwnerName"] = resolved_name
    if owner_company and not data.get("OwnerCompany"):
        data["OwnerCompany"] = owner_company
    # 保存 HRDB userName_in_charge (用于权限匹配: 与登录用户 Username 比对)
    if owner_user_name and not data.get("OwnerUserName"):
        data["OwnerUserName"] = owner_user_name

    issue = Issue(**data, CreatedBy=current.Id)
    db.add(issue)
    db.flush()
    # 自动填充 Deadline (阶段实际审核完成日期 + 10 自然日; 阶段未评审完成则保持空)
    try:
        from app.services.issue_deadline_service import backfill_issue_deadlines
        backfill_issue_deadlines(db, [issue])
    except Exception as exc:
        logger.warning("创建问题时自动填充 Deadline 失败 (issue_no={}): {}", issue.IssueNo, exc)
    _add_comment(
        db,
        issue,
        current,
        content=f"问题已创建: {issue.Title}" + (f" (责任人: {issue.OwnerName or '未指定'})" if issue.OwnerName else ""),
        action="create",
        to_status=issue.Status,
    )
    db.commit()
    db.refresh(issue)
    return issue


@router.put("/{issue_id}", response_model=IssueOut, summary="更新问题")
def update_issue(issue_id: int, payload: IssueUpdate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    # 行锁: 防止与评分回填/关闭审批并发时序错位
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)  # noqa: E712
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    # 权限: 管理员可管理所有问题, 其他评审员仅能管理自己登记的问题
    if current.Role != "admin" and issue.CreatedBy != current.Id:
        raise HTTPException(status_code=403, detail="无权修改他人登记的问题")
    from_status = issue.Status
    data = payload.model_dump(exclude_unset=True)
    # 状态变更从通用字段中弹出, 统一走评分管控服务层 (禁止盲写 Status 绕过快照)
    new_status = data.pop("Status", None)
    # Deadline 人工修改: 标记 Manual, 自动回填不再覆盖
    deadline_in_payload = "Deadline" in data
    changes = []
    for k, v in data.items():
        old = getattr(issue, k)
        if old != v:
            changes.append(f"{k}: {old} → {v}")
            setattr(issue, k, v)
    if deadline_in_payload:
        issue.DeadlineIsManual = True
    if new_status is not None and new_status != from_status:
        if new_status == "closed":
            # 统一关闭入口: Status=closed + ClosedAt + 快照评分 (必经)
            close_issue_with_snapshot(db, issue, operator=current)
        elif from_status == "closed":
            # 重开: 评分管控字段清零
            reopen_issue_and_reset_scores(db, issue)
        else:
            issue.Status = new_status
        changes.append(f"Status: {from_status} → {new_status}")
    if changes:
        _add_comment(
            db,
            issue,
            current,
            content="更新: " + "; ".join(changes),
            action="update",
        )
    db.commit()
    db.refresh(issue)
    return issue


@router.delete("/{issue_id}", summary="删除问题 (软删)")
def delete_issue(issue_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    # 权限: 管理员可删除所有问题, 其他评审员仅能删除自己登记的问题
    if current.Role != "admin" and issue.CreatedBy != current.Id:
        raise HTTPException(status_code=403, detail="无权删除他人登记的问题")
    issue.IsDeleted = True
    _add_comment(
        db,
        issue,
        current,
        content=f"问题已删除 (by {current.DisplayName or current.Username})",
        action="delete",
    )
    db.commit()
    return {"message": "问题已删除"}


@router.patch("/{issue_id}/status", response_model=IssueOut, summary="更新问题状态")
def update_issue_status(
    issue_id: int,
    payload: IssueStatusUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """更新状态: 自动记录状态变更历史评论

    关闭/重开统一走评分管控服务层函数:
    - → closed: close_issue_with_snapshot (保证 ScoreAtClosure 快照, 不遗漏)
    - closed → 其他: reopen_issue_and_reset_scores (评分管控字段清零)
    """
    # 行锁: 防止与评分回填/关闭审批并发时序错位
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)  # noqa: E712
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    from_status = issue.Status

    # 关闭和重开必须使用专用闭环接口; 禁止通过通用状态接口绕过审批。
    if payload.Status == "closed":
        if current.Role not in ("admin", "lead_reviewer"):
            raise HTTPException(status_code=403, detail="仅管理员或主审核员可以关闭问题")
        if from_status != "pending_verification":
            raise HTTPException(status_code=400, detail="问题必须先提交关闭申请后才能关闭")
    elif from_status == "closed":
        raise HTTPException(status_code=400, detail="已关闭问题请使用重开接口")
    elif payload.Status != "in_progress" or from_status not in ("open", "in_progress"):
        raise HTTPException(status_code=400, detail="非法的问题状态流转")

    if payload.Status == "closed":
        # 统一关闭入口: Status=closed + ClosedAt + 快照评分 (必经)
        close_issue_with_snapshot(
            db,
            issue,
            operator=current,
            verification_comments=payload.VerificationComments,
            closing_status=payload.ClosingStatus,
        )
    elif from_status == "closed":
        # 重开: 评分管控字段清零, 重新走整改闭环
        reopen_issue_and_reset_scores(db, issue)
        if payload.ClosingStatus is not None:
            issue.ClosingStatus = payload.ClosingStatus
        if payload.VerificationComments is not None:
            issue.VerificationComments = payload.VerificationComments
    else:
        issue.Status = payload.Status
        if payload.ClosingStatus is not None:
            issue.ClosingStatus = payload.ClosingStatus
        if payload.VerificationComments is not None:
            issue.VerificationComments = payload.VerificationComments

    comment_content = f"状态变更: {from_status} → {payload.Status}"
    if payload.VerificationComments:
        comment_content += f" | 意见: {payload.VerificationComments}"
    if payload.ClosingStatus:
        comment_content += f" | 闭环: {payload.ClosingStatus}"
    _add_comment(
        db,
        issue,
        current,
        content=comment_content,
        action="status_change",
        from_status=from_status,
        to_status=payload.Status,
    )
    db.commit()
    db.refresh(issue)
    return issue


@router.post(
    "/{issue_id}/verify",
    response_model=IssueOut,
    summary="验证问题 (lead_reviewer/admin)",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def verify_issue(
    issue_id: int,
    payload: IssueStatusUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """验证问题: 记录验证人/验证意见/验证时间, 并写入评论历史

    关闭/重开统一走评分管控服务层函数 (保证 ScoreAtClosure 快照不遗漏)。
    """
    # 行锁: 防止与评分回填并发时序错位
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)  # noqa: E712
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    from_status = issue.Status
    target_status = payload.Status or "pending_verification"

    if target_status == "closed":
        # 统一关闭入口: Status=closed + ClosedAt + VerifiedBy/At + 快照评分
        close_issue_with_snapshot(
            db,
            issue,
            operator=current,
            verification_comments=payload.VerificationComments,
            closing_status=payload.ClosingStatus,
        )
    elif from_status == "closed":
        # 重开: 评分管控字段清零, 记录验证人
        reopen_issue_and_reset_scores(db, issue)
        issue.VerifiedBy = current.Id
        issue.VerifiedAt = now_cst()
        if payload.VerificationComments is not None:
            issue.VerificationComments = payload.VerificationComments
        if payload.ClosingStatus is not None:
            issue.ClosingStatus = payload.ClosingStatus
    else:
        issue.Status = target_status
        issue.VerifiedBy = current.Id
        issue.VerifiedAt = now_cst()
        if payload.VerificationComments is not None:
            issue.VerificationComments = payload.VerificationComments
        if payload.ClosingStatus is not None:
            issue.ClosingStatus = payload.ClosingStatus

    comment_content = f"验证人: {current.DisplayName or current.Username}"
    if payload.VerificationComments:
        comment_content += f" | 意见: {payload.VerificationComments}"
    if payload.ClosingStatus:
        comment_content += f" | 闭环: {payload.ClosingStatus}"
    _add_comment(
        db,
        issue,
        current,
        content=comment_content,
        action="verify",
        from_status=from_status,
        to_status=issue.Status,
    )
    db.commit()
    db.refresh(issue)
    return issue


@router.post(
    "/{issue_id}/reopen",
    response_model=IssueOut,
    summary="重开已关闭问题 (admin/lead_reviewer)",
    dependencies=[Depends(require_role("admin", "lead_reviewer"))],
)
def reopen_issue(
    issue_id: int,
    payload: IssueReopen,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """重开已关闭问题 (清零重置法)

    - 状态回到 in_progress, 评分管控三字段 (ScoreAtClosure/ScoreAfterUpdate/ScoreUpdatedAt) 清零
    - 重开原因必填, 记入评论历史 (审计追溯依据)
    - 通知责任人 (站内 + 邮件)
    """
    # 行锁: 防止与评分回填并发时序错位
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)  # noqa: E712
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    if issue.Status != "closed":
        raise HTTPException(status_code=400, detail="仅已关闭的问题可以重开")

    from_status = issue.Status
    reopen_issue_and_reset_scores(db, issue)
    _add_comment(
        db,
        issue,
        current,
        content=f"问题已重开 | 原因: {payload.Reason}",
        action="reopen",
        from_status=from_status,
        to_status=issue.Status,
    )
    db.commit()
    db.refresh(issue)

    # 通知责任人 (站内 + 邮件), 失败不影响重开结果
    try:
        from app.api.workbench import _get_system_url
        from app.services.email_service import EmailService
        from app.services.notification_service import NotificationService

        notif_service = NotificationService(db, EmailService(settings))
        system_url = _get_system_url(db)
        ctx = {
            "issue_no": issue.IssueNo,
            "title": issue.Title,
            "owner_name": issue.OwnerName or "未指定",
            "reopen_by": current.DisplayName or current.Username,
            "reason": payload.Reason,
            "system_url": system_url,
        }
        recipient_id = issue.OwnerUserId
        if not recipient_id and issue.OwnerUserName:
            owner = db.query(User).filter(User.Username == issue.OwnerUserName).first()
            if owner:
                recipient_id = owner.Id
        if recipient_id:
            notif_service.create_and_email(
                user_id=recipient_id,
                title=f"问题已重开: {issue.Title}",
                content=(
                    f"您负责的问题已被审核员重开, 需继续整改\n"
                    f"问题编号: {issue.IssueNo}\n"
                    f"标题: {issue.Title}\n"
                    f"重开人: {current.DisplayName or current.Username}\n"
                    f"重开原因: {payload.Reason}\n"
                    f"请登录系统继续维护整改信息"
                ),
                notif_type="issue_reopened",
                link=f"/issues?issue_id={issue.Id}",
                template_key="issue_reopened",
                context=ctx,
                ref_type="issue",
                ref_id=issue.Id,
            )
            logger.info(
                "问题重开通知已发送给责任人 user_id={} (issue_id={})",
                recipient_id, issue.Id,
            )
    except Exception:
        logger.exception("问题重开通知发送失败 (issue_id={})", issue.Id)

    return issue


# ============ 问题评论 (跟踪历史) ============

@router.get(
    "/{issue_id}/comments",
    response_model=list[IssueCommentOut],
    summary="问题评论历史",
)
def list_issue_comments(
    issue_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回该问题的全部评论/操作历史 (按时间正序)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    comments = (
        db.query(IssueComment)
        .filter(IssueComment.IssueId == issue_id)
        .order_by(IssueComment.CreatedAt.asc(), IssueComment.Id.asc())
        .all()
    )
    return comments


@router.post(
    "/{issue_id}/comments",
    response_model=IssueCommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增问题评论",
)
def add_issue_comment(
    issue_id: int,
    payload: IssueCommentCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """新增评论 (用于补充整改说明、追问、回复等)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    comment = IssueComment(
        IssueId=issue_id,
        AuthorUserId=current.Id,
        AuthorName=current.DisplayName or current.Username,
        Action=payload.Action,
        Content=payload.Content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


# ============ 审核证据附件 ============

@router.get(
    "/{issue_id}/evidence",
    response_model=list[AttachmentOut],
    summary="问题审核证据附件列表",
)
def list_issue_evidence(
    issue_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回该问题的全部审核证据附件 (审核员登记问题时上传)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    return _list_issue_attachments(db, issue_id)


@router.get(
    "/{issue_id}/closure-evidence",
    response_model=list[AttachmentOut],
    summary="问题关闭证据附件列表",
)
def list_issue_closure_evidence(
    issue_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回该问题的全部关闭证据附件 (被审核人申请关闭时上传)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    return _list_issue_closure_attachments(db, issue_id)


@router.delete(
    "/{issue_id}/closure-evidence/{attachment_id}",
    summary="删除问题关闭证据 (仅责任人/管理员)",
)
def delete_issue_closure_evidence(
    issue_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """删除关闭证据附件 (仅责任人本人或管理员可删除)"""
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()  # noqa: E712
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")
    # 权限: admin 可删除, 否则仅责任人本人可删除
    is_owner = (
        issue.OwnerUserId == current.Id
        or (issue.OwnerUserName and issue.OwnerUserName == current.Username)
    )
    if current.Role != "admin" and not is_owner:
        raise HTTPException(status_code=403, detail="无权删除他人的关闭证据")
    att = (
        db.query(Attachment)
        .filter(
            Attachment.Id == attachment_id,
            Attachment.OwnerType == "issue_closure",
            Attachment.OwnerId == issue_id,
        )
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="关闭证据不存在")
    # 删除物理文件
    try:
        path = Path(att.StoredPath)
        if path.exists():
            path.unlink()
    except OSError:
        pass
    db.delete(att)
    db.commit()
    return {"message": "关闭证据已删除"}
