"""我的工作台路由

角色区分:
- reviewee (被审核人/ME): 我的项目库 + 审核问题列表
- admin/lead_reviewer (管理员/主审核员): 待关闭审批列表
"""
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import func as sqlfunc
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.historic_score import HistoricScore
from app.models.issue import Issue
from app.models.review import ReviewRecord
from app.models.user import User
from app.schemas.common import PageResponse
from app.schemas.issue import (
    IssueClosureApproval,
    IssueClosureRequest,
    IssueOut,
    IssueWorkbenchUpdate,
)
from app.services.email_service import EmailService
from app.services.hrdb_query_service import HrdbQueryService
from app.services.issue_project_service import attach_project_names
from app.services.notification_service import NotificationService
from app.services.score_control_service import close_issue_with_snapshot
from app.utils.pagination import paginate
from app.utils.time import now_cst

router = APIRouter(prefix="/api/workbench", tags=["我的工作台"])


def _get_hrdb_service() -> HrdbQueryService:
    return HrdbQueryService(settings)


def _get_email_service() -> EmailService:
    return EmailService(settings)


def _get_notification_service(db: Session) -> NotificationService:
    return NotificationService(db, _get_email_service())


# 通知模式由 config.ini [notification].mode 控制:
# - test (测试模式): 邮件由 EmailService 自动重定向到 NOTIFICATION_TEST_RECIPIENTS
#   此处额外将审批结果副本发送给管理员 (站内通知 + 邮件), 便于验证功能可用
# - production (生产模式): 仅发送给真实责任人, 不再额外抄送管理员
# 站内通知 (铃铛) 始终发送给业务相关用户, 不受模式影响


def _get_admin_and_lead_users(db: Session) -> List[User]:
    """获取所有 admin 和 lead_reviewer 用户 (用于关闭申请通知)

    仅返回启用账户 (Status=1), 禁用账户不再接收通知邮件
    """
    return (
        db.query(User)
        .filter(User.Role.in_(["admin", "lead_reviewer"]))
        .filter(User.IsDeleted == False)  # noqa: E712
        .filter(User.Status == 1)
        .all()
    )


def _is_notification_test_mode(db: Session) -> bool:
    """查询运行时通知模式 (数据库 SystemSetting 优先, 其次 config.ini)

    用于决定是否将审批结果副本发送给管理员。
    EmailService.send_email 内部也会独立查询, 这里查询仅用于决定是否触发副本通知。
    """
    try:
        from app.models.system_setting import SystemSetting

        row = (
            db.query(SystemSetting)
            .filter(SystemSetting.SettingKey == "notification_mode")
            .first()
        )
        if row and row.SettingValue:
            return row.SettingValue.strip().lower() == "test"
    except Exception:
        pass
    # 回退到 config.ini 默认值
    return settings.is_notification_test_mode


def _get_system_url(db: Optional[Session] = None) -> str:
    """获取系统访问 URL (用于邮件正文中的 "访问地址" 链接)

    优先级: 数据库 SystemSetting > settings.SYSTEM_URL > CORS_ORIGINS 第一项 > host/port 构造
    修改后立即生效, 无需重启服务。
    """
    # 优先从数据库读取
    if db is not None:
        try:
            from app.services.system_config_service import get_string
            url = get_string(db, "system_url")
            if url:
                return url
        except Exception:
            pass
    # 回退到 config.ini
    url = settings.effective_system_url
    if url:
        return url
    # 兜底: 基于 host/port 构造 (开发环境)
    host = settings.APP_HOST or "localhost"
    port = settings.APP_PORT or 8000
    if host == "0.0.0.0":
        host = "localhost"
    return f"http://{host}:{port}/"


def _attach_item_names(db: Session, items: list[IssueOut]) -> None:
    """为问题列表注入检查项具体内容 (ItemName)

    复用邮件场景的解析逻辑 (app.services.issue_deadline_service):
    优先按 Issue.ItemId 关联 CheckItem.Id; 未关联的按规范化
    (PhaseCode, ItemNo) 键匹配。未命中时保持为空, 不做占位填充。
    """
    from app.services.issue_deadline_service import _load_check_item_names

    # _load_check_item_names 按 Issue 模型属性读取 (ItemId/PhaseCode/ItemNo),
    # IssueOut 同名字段结构一致, 可直接复用
    names = _load_check_item_names(db, items)  # noqa: SLF001
    for it in items:
        if not (it.ItemName or "").strip():
            it.ItemName = names.get(it.Id) or ""


# ============ 我的项目库 (被审核人/ME) ============

@router.get("/my-projects", summary="我的项目库 - 当前用户负责的 MSIA 项目")
def get_my_projects(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> List[dict[str, Any]]:
    """获取当前登录用户负责的所有 MSIA 项目, 含各阶段评审汇总

    匹配规则: HRDB msia_plan 中 userName_in_charge 对应 fine_user.userName,
    再通过 fine_user.userName 与当前用户 Username 匹配。
    若当前用户是 admin, 则返回所有项目。
    """
    service = _get_hrdb_service()

    # admin 查看所有项目
    if current.Role == "admin":
        from app.api.msia_plan import list_msia_plans
        # 直接查询全部 (page_size=200 足够)
        result = service.query_msia_plans(keyword=None, order_id=None, page=1, page_size=200)
        project_list = result.get("items", []) if isinstance(result, dict) else []
    else:
        # 普通用户: 按用户名匹配负责人
        result = service.query_msia_plans(keyword=None, order_id=None, page=1, page_size=500)
        all_projects = result.get("items", []) if isinstance(result, dict) else []

        # 匹配当前用户 (Username 或 DisplayName)
        project_list = []
        for item in all_projects:
            owner_name = item.get("ownerName") or ""
            real_name = item.get("realName") or ""
            user_name_in_charge = item.get("userName_in_charge") or ""
            name_in_charge = item.get("name_in_charge") or ""

            # 多种匹配方式
            if (user_name_in_charge == current.Username or
                owner_name == (current.DisplayName or "") or
                real_name == (current.DisplayName or "") or
                name_in_charge == (current.DisplayName or "")):
                project_list.append(item)

    # 为每个项目查询各阶段评审汇总
    results: List[dict[str, Any]] = []
    for proj in project_list:
        plan_id = str(proj.get("planId", ""))
        if not plan_id:
            continue

        # 批量查询 MSIA1-5 评审汇总
        phase_summaries = []
        for i in range(1, 6):
            phase_code = f"MSIA{i}"
            subq = (
                db.query(
                    ReviewRecord.PhaseReviewItemId,
                    sqlfunc.max(ReviewRecord.Id).label("max_id"),
                )
                .filter(
                    ReviewRecord.PhaseCode == phase_code,
                    ReviewRecord.Score.isnot(None),
                    ReviewRecord.PlanId == plan_id,
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
                phase_summaries.append({
                    "phase": phase_code,
                    "phase_num": i,
                    "avg_score": round(avg, 4),
                    "avg_percent": round(avg * 100, 1),
                    "item_count": len(scores),
                    "source": "review",
                })
            else:
                # 无逐条评审记录, 回退到历史评分录入
                historic = (
                    db.query(HistoricScore)
                    .filter(
                        HistoricScore.PlanId == plan_id,
                        HistoricScore.PhaseCode == phase_code,
                    )
                    .first()
                )
                if historic:
                    h_score = float(historic.Score)
                    phase_summaries.append({
                        "phase": phase_code,
                        "phase_num": i,
                        "avg_score": h_score,
                        "avg_percent": round(h_score * 100, 1),
                        "item_count": 1,
                        "source": "historic",
                    })
                else:
                    phase_summaries.append({
                        "phase": phase_code,
                        "phase_num": i,
                        "avg_score": None,
                        "avg_percent": None,
                        "item_count": 0,
                        "source": None,
                    })

        # 查询该项目的问题数
        issue_count = db.query(sqlfunc.count(Issue.Id)).filter(
            Issue.PlanId == plan_id,
            Issue.IsDeleted == False,
        ).scalar() or 0

        # 计算总体平均分
        scored_phases = [p for p in phase_summaries if p["avg_score"] is not None]
        overall_avg = None
        if scored_phases:
            overall_avg = round(sum(p["avg_score"] for p in scored_phases) / len(scored_phases), 4)

        results.append({
            "planId": proj.get("planId"),
            "orderId": proj.get("orderId"),
            "projectName": proj.get("projectName"),
            "order_description": proj.get("order_description"),
            "lineType": proj.get("lineType"),
            "ownerName": proj.get("ownerName"),
            "leadUser": proj.get("leadUser"),
            "plantName": proj.get("plantName"),
            "lineName": proj.get("lineName"),
            "issueDate": proj.get("issueDate"),
            "endDate": proj.get("endDate"),
            "phases": phase_summaries,
            "overall_avg_score": overall_avg,
            "overall_avg_percent": round(overall_avg * 100, 1) if overall_avg is not None else None,
            "issue_count": issue_count,
        })

    return results


# ============ 我的审核问题列表 (被审核人/ME) ============

@router.get("/my-issues", summary="我的审核问题列表 - 当前用户负责的问题")
def get_my_issues(
    plan_id: str = Query(None, description="按 MSIA 计划 ID 筛选"),
    phase_code: str = Query(None, description="按阶段筛选 (MSIA1~MSIA5)"),
    status: str = Query(None, description="按状态筛选"),
    keyword: str = Query(None, description="按问题名称模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> PageResponse[IssueOut]:
    """获取当前用户负责的所有审核问题

    规则:
    - reviewee: 仅返回与当前用户相关的问题
        - OwnerUserId = 当前用户.Id (已关联本地用户)
        - OR OwnerUserName = 当前用户.Username (来自 HRDB userName_in_charge)
    - admin/lead_reviewer/reviewer: 返回所有问题 (便于全局查看)
    """
    query = db.query(Issue).filter(Issue.IsDeleted == False)

    # 权限: reviewee 只看自己的, 其他角色看全部
    if current.Role == "reviewee":
        query = query.filter(
            or_(
                Issue.OwnerUserId == current.Id,
                Issue.OwnerUserName == current.Username,
            )
        )

    # 筛选
    if plan_id:
        query = query.filter(Issue.PlanId == plan_id)
    if phase_code:
        query = query.filter(Issue.PhaseCode == phase_code)
    if status:
        if status == "overdue":
            # 逾期筛选: 统一调用 issue_overdue 服务, 与看板统计/升级扫描口径一致
            from app.services.issue_overdue import build_overdue_filter

            query = query.filter(*build_overdue_filter(db=db))
        else:
            query = query.filter(Issue.Status == status)
    if keyword:
        query = query.filter(Issue.Title.like(f"%{keyword.strip()}%"))

    query = query.order_by(Issue.UpdatedAt.desc())
    page_data = paginate(query, page, page_size, IssueOut)
    # 注入项目名称 (HRDB) 与检查项内容 (评分条款定位), 便于责任人辨别问题来源
    if page_data.items:
        attach_project_names(db, page_data.items)
        _attach_item_names(db, page_data.items)
    return page_data


@router.get("/my-issues/filters", summary="审核问题列表筛选选项 (项目)")
def get_my_issue_filters(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    """返回当前用户可见问题关联的项目列表 (planId + 项目名称), 供前端项目筛选下拉"""
    query = db.query(Issue.PlanId).filter(
        Issue.IsDeleted == False,  # noqa: E712
        Issue.PlanId.isnot(None),
        Issue.PlanId != "",
    )
    # 权限口径与 my-issues 一致: reviewee 只看自己的
    if current.Role == "reviewee":
        query = query.filter(
            or_(
                Issue.OwnerUserId == current.Id,
                Issue.OwnerUserName == current.Username,
            )
        )
    plan_ids = {str(row[0]).strip() for row in query.distinct().all() if row[0]}
    if not plan_ids:
        return {"projects": []}

    projects: list[dict] = []
    try:
        service = _get_hrdb_service()
        infos = service.query_plan_owner_infos(sorted(plan_ids))
        for pid in sorted(plan_ids):
            name = (infos.get(pid) or {}).get("projectName") or ""
            if name:
                projects.append({"value": pid, "label": name})
    except Exception as exc:
        logger.warning("审核问题列表筛选选项查询失败 (HRDB): {}", exc)
        return {"projects": []}
    # 按项目名称排序, 便于下拉查找
    projects.sort(key=lambda p: p["label"])
    return {"projects": projects}


# ============ 待关闭审批列表 (管理员/主审核员) ============

@router.get("/pending-closures", summary="待关闭审批列表")
def get_pending_closures(
    phase_code: str = Query(None, description="按阶段筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin", "lead_reviewer")),
) -> PageResponse[IssueOut]:
    """获取所有待关闭审批的问题 (status = pending_verification)

    仅 admin/lead_reviewer 可访问。
    """
    query = db.query(Issue).filter(
        Issue.IsDeleted == False,
        Issue.Status == "pending_verification",
    )
    if phase_code:
        query = query.filter(Issue.PhaseCode == phase_code)
    query = query.order_by(Issue.ClosureRequestedAt.desc())
    page_data = paginate(query, page, page_size, IssueOut)
    # 注入项目名称与检查项内容, 便于审批人辨别问题归属项目与来源条款
    if page_data.items:
        attach_project_names(db, page_data.items)
        _attach_item_names(db, page_data.items)
    return page_data


# ============ 工作台更新问题 (被审核人维护原因/措施/计划日期) ============

@router.put("/issues/{issue_id}/workbench-update", summary="工作台更新问题")
def workbench_update_issue(
    issue_id: int,
    payload: IssueWorkbenchUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict[str, Any]:
    """被审核人在工作台维护问题的原因分析、纠正措施、计划完成日期

    权限:
    - admin: 可更新所有问题
    - reviewee: 仅可更新自己负责的问题
        - OwnerUserId = 当前用户.Id (已关联本地用户)
        - OR OwnerUserName = 当前用户.Username (来自 HRDB)
    """
    issue = db.query(Issue).filter(Issue.Id == issue_id, Issue.IsDeleted == False).first()
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")

    # 权限检查: admin 可操作所有, 其他用户仅操作属于自己的
    if current.Role != "admin":
        is_owner = (
            issue.OwnerUserId == current.Id
            or (issue.OwnerUserName and issue.OwnerUserName == current.Username)
        )
        if not is_owner:
            raise HTTPException(status_code=403, detail="无权更新此问题")

    # 更新字段
    changed_fields = []
    if payload.RootCause is not None:
        issue.RootCause = payload.RootCause or None
        changed_fields.append("RootCause")
    if payload.CorrectiveAction is not None:
        issue.CorrectiveAction = payload.CorrectiveAction or None
        changed_fields.append("CorrectiveAction")
    if payload.PlannedCloseDate is not None:
        issue.PlannedCloseDate = payload.PlannedCloseDate
        changed_fields.append("PlannedCloseDate")
    if payload.OwnerName is not None:
        issue.OwnerName = payload.OwnerName or None
        changed_fields.append("OwnerName")
    if payload.OwnerDepartment is not None:
        issue.OwnerDepartment = payload.OwnerDepartment or None
        changed_fields.append("OwnerDepartment")

    # 如果问题还是 open 状态, 且有措施/原因填写, 自动变为 in_progress
    if issue.Status == "open" and (issue.CorrectiveAction or issue.RootCause):
        issue.Status = "in_progress"
        changed_fields.append("Status→in_progress")

    db.commit()
    db.refresh(issue)
    return {"ok": True, "id": issue.Id, "changed": changed_fields}


# ============ 申请关闭问题 (被审核人提交) ============

@router.post("/issues/{issue_id}/request-closure", summary="申请关闭问题")
def request_closure(
    issue_id: int,
    payload: IssueClosureRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict[str, Any]:
    """被审核人提交关闭申请, 问题状态变为 pending_verification

    前置条件:
    - 原因分析 / 纠正措施为选填, 未填写也可申请关闭
    - 问题状态不能是 closed
    - 权限: admin 可操作所有, 其他用户仅操作属于自己的问题
        - OwnerUserId = 当前用户.Id (已关联本地用户)
        - OR OwnerUserName = 当前用户.Username (来自 HRDB)
    """
    # 行锁: 防止并发申请关闭同一问题导致重复发送邮件
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")

    # 权限: admin 可操作所有, 其他用户仅操作属于自己的
    if current.Role != "admin":
        is_owner = (
            issue.OwnerUserId == current.Id
            or (issue.OwnerUserName and issue.OwnerUserName == current.Username)
        )
        if not is_owner:
            raise HTTPException(status_code=403, detail="无权操作此问题")

    if issue.Status == "closed":
        raise HTTPException(status_code=400, detail="问题已关闭, 无需再次申请")

    # 幂等性检查: 已经在待审批状态, 不允许重复申请 (防止重复发送邮件)
    if issue.Status == "pending_verification":
        raise HTTPException(
            status_code=400,
            detail="该问题已提交关闭申请, 正在等待审核员审批, 请勿重复提交",
        )

    # 更新状态
    issue.Status = "pending_verification"
    issue.ClosureRequestedAt = now_cst()
    issue.ClosureRequestedBy = current.Id
    if payload.VerificationComments:
        issue.VerificationComments = payload.VerificationComments

    db.commit()
    db.refresh(issue)

    # ============ 通知: 站内 + 邮件 给管理员 / Lead 审核员 ============
    try:
        notif_service = _get_notification_service(db)
        system_url = _get_system_url(db)
        # 申请人姓名 (用于邮件内容)
        requester_name = current.DisplayName or current.Username
        # 关闭申请时间格式化
        closure_requested_at = (
            issue.ClosureRequestedAt.strftime("%Y-%m-%d %H:%M")
            if issue.ClosureRequestedAt
            else ""
        )
        # 邮件上下文
        ctx = {
            "issue_no": issue.IssueNo,
            "title": issue.Title,
            "owner_name": issue.OwnerName or "未指定",
            "severity": issue.Severity or "M",
            "plant": issue.OwnerCompany or "未指定",
            "phase_code": issue.PhaseCode or "",
            "item_no": issue.ItemNo or "",
            "closure_requested_at": closure_requested_at,
            "requester_name": requester_name,
            "system_url": system_url,
        }
        # 通知所有 admin / lead_reviewer
        # 邮件合并为一封 (收件人为全部审核员), 避免测试模式下同一邮箱收到多封重复邮件
        reviewers = _get_admin_and_lead_users(db)
        notif_service.create_and_email_group(
            user_ids=[r.Id for r in reviewers],
            title=f"问题关闭申请待审批: {issue.Title}",
            content=(
                f"责任人 {issue.OwnerName or '未指定'} 已提交问题关闭申请\n"
                f"问题编号: {issue.IssueNo}\n"
                f"标题: {issue.Title}\n"
                f"申请人: {requester_name}\n"
                f"关闭申请时间: {closure_requested_at}\n"
                f"请尽快登录系统检查问题是否可以关闭"
            ),
            notif_type="issue_closure_requested",
            link=f"/issues?issue_id={issue.Id}",
            template_key="issue_closure_requested",
            context=ctx,
            ref_type="issue",
            ref_id=issue.Id,
        )
        logger.info(
            "关闭申请通知已发送给 {} 位审核员 (issue_id={})",
            len(reviewers), issue.Id,
        )
    except Exception:
        logger.exception("关闭申请通知发送失败 (issue_id={})", issue.Id)

    return {"ok": True, "id": issue.Id, "status": issue.Status}


# ============ 审批关闭申请 (管理员/主审核员) ============

@router.post("/issues/{issue_id}/approve-closure", summary="审批关闭申请")
def approve_closure(
    issue_id: int,
    payload: IssueClosureApproval,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin", "lead_reviewer")),
) -> dict[str, Any]:
    """管理员/主审核员审批关闭申请

    - Approved=True: 关闭问题, 状态变为 closed
    - Approved=False: 驳回, 状态回退为 in_progress

    幂等性保护: 使用 SELECT FOR UPDATE 行锁, 防止并发请求重复审批
    (前端虽然做了防重复点击, 后端仍需兜底防止并发导致重复发送邮件)
    """
    # 行锁: 防止并发审批同一问题导致重复发送邮件
    issue = (
        db.query(Issue)
        .filter(Issue.Id == issue_id, Issue.IsDeleted == False)
        .with_for_update()
        .first()
    )
    if not issue:
        raise HTTPException(status_code=404, detail="问题不存在")

    if issue.Status != "pending_verification":
        raise HTTPException(status_code=400, detail="该问题当前不在待审批状态")

    if payload.Approved:
        # 批准关闭: 统一关闭入口 (Status + ClosedAt + VerifiedBy/At + 快照评分)
        close_issue_with_snapshot(
            db,
            issue,
            operator=current,
            verification_comments=payload.VerificationComments,
        )
        message = "问题已关闭"
        template_key = "issue_closure_approved"
        notif_type = "issue_closure_approved"
        notif_title = f"问题已关闭: {issue.Title}"
        notif_content = (
            f"您提交的问题关闭申请已通过审批\n"
            f"问题编号: {issue.IssueNo}\n"
            f"标题: {issue.Title}\n"
            f"审批人: {current.DisplayName or current.Username}\n"
            f"审核意见: {payload.VerificationComments or '无'}"
        )
    else:
        # 驳回
        issue.Status = "in_progress"
        if payload.VerificationComments:
            issue.VerificationComments = payload.VerificationComments
        message = "关闭申请已驳回, 问题回到处理中状态"
        template_key = "issue_closure_rejected"
        notif_type = "issue_closure_rejected"
        notif_title = f"问题关闭申请被驳回: {issue.Title}"
        notif_content = (
            f"您提交的问题关闭申请已被驳回\n"
            f"问题编号: {issue.IssueNo}\n"
            f"标题: {issue.Title}\n"
            f"审批人: {current.DisplayName or current.Username}\n"
            f"审核意见: {payload.VerificationComments or '无'}\n"
            f"请根据审核意见继续整改, 完成后再次申请关闭"
        )

    db.commit()
    db.refresh(issue)

    # ============ 通知: 站内 + 邮件 给责任人 ============
    # 测试模式 (settings.is_notification_test_mode):
    #   - 邮件由 EmailService 自动重定向到 NOTIFICATION_TEST_RECIPIENTS
    #   - 此处额外将副本发送给管理员 (站内通知 + 邮件), 便于验证功能可用
    # 生产模式: 仅发送给真实责任人, 不再额外抄送管理员
    # 站内通知 (铃铛) 始终发送给业务相关用户, 不受模式影响
    try:
        notif_service = _get_notification_service(db)
        system_url = _get_system_url(db)
        reviewer_name = current.DisplayName or current.Username
        closed_at_str = (
            issue.ClosedAt.strftime("%Y-%m-%d %H:%M")
            if issue.ClosedAt
            else ""
        )
        ctx = {
            "issue_no": issue.IssueNo,
            "title": issue.Title,
            "owner_name": issue.OwnerName or "未指定",
            "severity": issue.Severity or "M",
            "plant": issue.OwnerCompany or "未指定",
            "phase_code": issue.PhaseCode or "",
            "item_no": issue.ItemNo or "",
            "reviewer_name": reviewer_name,
            "verification_comments": payload.VerificationComments or "无",
            "closed_at": closed_at_str,
            "system_url": system_url,
        }

        # 1. 站内通知 + 邮件: 责任人 (通过 OwnerUserId 关联本地用户)
        recipient_id = issue.OwnerUserId
        if not recipient_id and issue.OwnerUserName:
            # 通过 OwnerUserName 查找本地用户
            owner = db.query(User).filter(User.Username == issue.OwnerUserName).first()
            if owner:
                recipient_id = owner.Id

        if recipient_id:
            notif_service.create_and_email(
                user_id=recipient_id,
                title=notif_title,
                content=notif_content,
                notif_type=notif_type,
                link=f"/issues?issue_id={issue.Id}",
                template_key=template_key,
                context=ctx,
                ref_type="issue",
                ref_id=issue.Id,
            )
            logger.info(
                "关闭审批结果通知已发送给责任人 user_id={} (issue_id={}, approved={})",
                recipient_id, issue.Id, payload.Approved,
            )

        # 2. 测试模式: 副本发送给管理员 (EmailService 会自动重定向到测试邮箱)
        # 邮件合并为一封, 避免测试模式下同一邮箱收到多封重复邮件
        if _is_notification_test_mode(db):
            admins = _get_admin_and_lead_users(db)
            notif_service.create_and_email_group(
                user_ids=[a.Id for a in admins],
                title=f"[测试副本] {notif_title}",
                content=notif_content,
                notif_type=notif_type,
                link=f"/issues?issue_id={issue.Id}",
                template_key=template_key,
                context=ctx,
                ref_type="issue",
                ref_id=issue.Id,
                skip_user_ids=[recipient_id] if recipient_id else None,
            )
            logger.info(
                "测试模式: 关闭审批结果副本已合并发送给 {} 位管理员 (issue_id={})",
                len(admins), issue.Id,
            )
    except Exception:
        logger.exception("关闭审批结果通知发送失败 (issue_id={})", issue.Id)

    return {"ok": True, "id": issue.Id, "status": issue.Status, "message": message}
