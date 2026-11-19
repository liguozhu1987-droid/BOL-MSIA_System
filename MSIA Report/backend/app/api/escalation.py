"""问题升级配置路由

功能:
- 升级配置 CRUD (按 工厂 × 严重等级 唯一)
- 升级日志查询
- 升级统计
- 手动触发升级扫描 (管理员)

权限:
- 仅 admin 可管理配置
- admin/lead_reviewer 可查看日志
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, func as sqlfunc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.escalation_config import EscalationConfig, EscalationLog
from app.models.issue import Issue
from app.models.user import User
from app.schemas.common import PageResponse
from app.schemas.escalation import (
    EscalationConfigCreate,
    EscalationConfigOut,
    EscalationConfigUpdate,
    EscalationLogOut,
    EscalationLogStatsOut,
    TestEmailRequest,
    TestEmailResponse,
)
from app.utils.pagination import paginate
from app.utils.time import now_cst

router = APIRouter(prefix="/api/escalation", tags=["问题升级"])


# ============ 升级配置管理 ============

@router.get(
    "/configs",
    response_model=PageResponse[EscalationConfigOut],
    summary="升级配置列表",
)
def list_configs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    plant: str | None = Query(None, description="按工厂筛选"),
    severity: str | None = Query(None, description="按等级筛选 (H/M/L)"),
    enabled: bool | None = Query(None, description="按启用状态筛选"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(EscalationConfig)
    if plant:
        query = query.filter(EscalationConfig.Plant == plant)
    if severity:
        query = query.filter(EscalationConfig.Severity == severity)
    if enabled is not None:
        query = query.filter(EscalationConfig.IsEnabled == enabled)
    query = query.order_by(EscalationConfig.Plant.asc(), EscalationConfig.Severity.asc())
    return paginate(query, page, page_size, EscalationConfigOut)


@router.get(
    "/configs/all",
    response_model=list[EscalationConfigOut],
    summary="全部升级配置 (不分页)",
)
def list_all_configs(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回全部启用配置, 便于前端下拉选择"""
    return db.query(EscalationConfig).order_by(
        EscalationConfig.Plant.asc(), EscalationConfig.Severity.asc()
    ).all()


@router.post(
    "/configs",
    response_model=EscalationConfigOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建升级配置",
    dependencies=[Depends(require_role("admin"))],
)
def create_config(
    payload: EscalationConfigCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # 唯一性校验: Plant + Severity
    exists = db.query(EscalationConfig).filter(
        EscalationConfig.Plant == payload.Plant,
        EscalationConfig.Severity == payload.Severity,
    ).first()
    if exists:
        raise HTTPException(
            status_code=400,
            detail=f"配置已存在: Plant={payload.Plant}, Severity={payload.Severity}",
        )
    config = EscalationConfig(**payload.model_dump(), CreatedBy=current.Id)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.put(
    "/configs/{config_id}",
    response_model=EscalationConfigOut,
    summary="更新升级配置",
    dependencies=[Depends(require_role("admin"))],
)
def update_config(
    config_id: int,
    payload: EscalationConfigUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    config = db.query(EscalationConfig).filter(EscalationConfig.Id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    data = payload.model_dump(exclude_unset=True)

    # Plant / Severity 变更校验
    from app.schemas.escalation import SEVERITIES

    new_plant = data.get("Plant", config.Plant)
    new_severity = data.get("Severity", config.Severity)
    if new_severity not in SEVERITIES:
        raise HTTPException(status_code=400, detail=f"Severity 必须是 {SEVERITIES} 之一")
    if (new_plant, new_severity) != (config.Plant, config.Severity):
        exists = db.query(EscalationConfig).filter(
            EscalationConfig.Plant == new_plant,
            EscalationConfig.Severity == new_severity,
            EscalationConfig.Id != config_id,
        ).first()
        if exists:
            raise HTTPException(
                status_code=400,
                detail=f"配置已存在: Plant={new_plant}, Severity={new_severity}",
            )

    # 联合校验: 小时数须递增
    l1 = data.get("Level1Hours", config.Level1Hours)
    l2 = data.get("Level2Hours", config.Level2Hours)
    l3 = data.get("Level3Hours", config.Level3Hours)
    if not (l1 < l2 < l3):
        raise HTTPException(
            status_code=400,
            detail="触发小时数须满足 Level1Hours < Level2Hours < Level3Hours",
        )
    for k, v in data.items():
        setattr(config, k, v)
    db.commit()
    db.refresh(config)
    return config


@router.delete(
    "/configs/{config_id}",
    summary="删除升级配置",
    dependencies=[Depends(require_role("admin"))],
)
def delete_config(
    config_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    config = db.query(EscalationConfig).filter(EscalationConfig.Id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    db.delete(config)
    db.commit()
    return {"message": "配置已删除"}


@router.post(
    "/configs/{config_id}/toggle",
    response_model=EscalationConfigOut,
    summary="启用/禁用升级配置",
    dependencies=[Depends(require_role("admin"))],
)
def toggle_config(
    config_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    config = db.query(EscalationConfig).filter(EscalationConfig.Id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    config.IsEnabled = not config.IsEnabled
    db.commit()
    db.refresh(config)
    return config


# ============ 升级日志查询 ============

def _load_issue_context(db: Session, items: list) -> None:
    """为日志条目注入问题扩展字段: 编号/标题/工厂/等级/责任人/项目名称"""
    if not items:
        return
    issue_ids = [it.IssueId for it in items]
    issues = db.query(Issue).filter(Issue.Id.in_(issue_ids)).all()
    issue_map = {i.Id: i for i in issues}
    # 注入项目名称 (HRDB, 单次连接批量)
    from app.services.issue_project_service import attach_project_names

    attach_project_names(db, list(issue_map.values()))
    for it in items:
        iss = issue_map.get(it.IssueId)
        if iss:
            it.IssueNo = iss.IssueNo
            it.IssueTitle = iss.Title
            it.Plant = iss.OwnerCompany
            it.Severity = iss.Severity
            it.OwnerName = iss.OwnerName or iss.OwnerUserName or ""
            it.ProjectName = getattr(iss, "ProjectName", "") or ""


@router.get(
    "/logs",
    response_model=PageResponse[EscalationLogOut],
    summary="升级日志列表",
)
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    issue_id: int | None = Query(None, description="按问题ID筛选"),
    level: int | None = Query(None, description="按升级级别筛选 (1/2/3)"),
    plant: str | None = Query(None, description="按工厂筛选"),
    owner_name: str | None = Query(None, description="按责任人筛选 (姓名/账号模糊匹配)"),
    project_name: str | None = Query(None, description="按项目名称筛选 (模糊匹配)"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(EscalationLog).join(
        Issue, EscalationLog.IssueId == Issue.Id, isouter=True
    )
    if issue_id:
        query = query.filter(EscalationLog.IssueId == issue_id)
    if level:
        query = query.filter(EscalationLog.Level == level)
    if plant:
        query = query.filter(Issue.OwnerCompany == plant)
    if owner_name:
        query = query.filter(
            or_(
                Issue.OwnerName.like(f"%{owner_name}%"),
                Issue.OwnerUserName.like(f"%{owner_name}%"),
            )
        )
    if project_name:
        # 项目名称来自 HRDB: 先取日志关联问题的 PlanId, 反查项目名后按名称匹配
        plan_ids = {
            str(pid).strip()
            for (pid,) in db.query(Issue.PlanId).filter(
                Issue.PlanId.isnot(None), Issue.PlanId != ""
            ).distinct().all()
            if pid
        }
        matched: set[str] = set()
        if plan_ids:
            from app.core.config import settings as app_settings
            from app.services.hrdb_query_service import HrdbQueryService

            try:
                service = HrdbQueryService(app_settings)
                infos = service.query_plan_owner_infos(sorted(plan_ids))
                keyword = project_name.strip().lower()
                matched = {
                    pid
                    for pid, info in infos.items()
                    if keyword in (info.get("projectName") or "").lower()
                }
            except Exception:
                matched = set()
        if matched:
            query = query.filter(Issue.PlanId.in_(sorted(matched)))
        else:
            # 无匹配项目 → 空结果
            query = query.filter(EscalationLog.Id < 0)
    # 默认按发送时间倒序 (最新在前)
    query = query.order_by(EscalationLog.SentAt.desc(), EscalationLog.Id.desc())
    page_data = paginate(query, page, page_size, EscalationLogOut)
    _load_issue_context(db, page_data.items)
    return page_data


@router.get(
    "/logs/filters",
    summary="升级日志筛选选项 (责任人 / 项目列表)",
)
def get_log_filters(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回有升级日志的问题对应的责任人与项目选项, 供前端筛选下拉"""
    issue_ids = [
        row[0]
        for row in db.query(EscalationLog.IssueId).distinct().all()
    ]
    if not issue_ids:
        return {"owners": [], "projects": []}
    issues = db.query(Issue).filter(Issue.Id.in_(issue_ids)).all()

    # 责任人去重 (优先中文姓名)
    owners = sorted({
        (i.OwnerName or i.OwnerUserName or "").strip()
        for i in issues
        if (i.OwnerName or i.OwnerUserName or "").strip()
    })

    # 项目名称 (HRDB 批量注入后去重)
    from app.services.issue_project_service import attach_project_names

    attach_project_names(db, issues)
    projects = sorted({
        getattr(i, "ProjectName", "").strip()
        for i in issues
        if getattr(i, "ProjectName", "").strip()
    })
    return {
        "owners": [{"value": o, "label": o} for o in owners],
        "projects": [{"value": p, "label": p} for p in projects],
    }


@router.get(
    "/logs/stats",
    response_model=EscalationLogStatsOut,
    summary="升级统计",
)
def get_log_stats(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    base = db.query(EscalationLog)
    total = base.count()
    level1 = base.filter(EscalationLog.Level == 1).count()
    level2 = base.filter(EscalationLog.Level == 2).count()
    level3 = base.filter(EscalationLog.Level == 3).count()
    # SentAt 为北京时间 (与库内其他时间字段口径一致), 统计也用北京时间
    now_cst_v = now_cst()
    last_24h = base.filter(EscalationLog.SentAt >= now_cst_v - timedelta(hours=24)).count()
    return EscalationLogStatsOut(
        total=total,
        level1_count=level1,
        level2_count=level2,
        level3_count=level3,
        last_24h_count=last_24h,
    )


# ============ 工厂列表 (辅助接口) ============

@router.get(
    "/plants",
    response_model=list[str],
    summary="获取已配置的工厂列表",
)
def list_plants(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """返回已配置的工厂去重列表, 便于前端下拉"""
    rows = db.query(EscalationConfig.Plant).distinct().all()
    return [r[0] for r in rows if r[0]]


# ============ 手动触发升级扫描 (管理员) ============

@router.post(
    "/scan",
    summary="手动触发升级扫描",
    dependencies=[Depends(require_role("admin"))],
)
def manual_scan(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """管理员手动触发一次升级扫描, 用于测试或即时通知"""
    from app.scheduler.scheduler import _scan_escalations
    result = _scan_escalations()
    return {"ok": True, "result": result}


# ============ 测试邮件连通性 (管理员) ============

@router.post(
    "/test-email",
    response_model=TestEmailResponse,
    summary="发送测试邮件, 验证 SMTP 邮箱服务连通性",
    dependencies=[Depends(require_role("admin"))],
)
def send_test_email(
    payload: TestEmailRequest,
    current: User = Depends(get_current_user),
):
    """管理员发送一封测试邮件, 验证系统邮箱服务 (SMTP) 是否连通可用。

    不依赖升级配置, 直接向指定收件人发送一封连通性测试邮件,
    返回 SMTP 配置信息与发送结果, 便于排查邮件服务问题。
    """
    import re

    from app.core.config import settings
    from app.services.email_service import EmailService

    # 基础校验邮箱格式
    email_regex = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    if not re.match(email_regex, payload.recipient.strip()):
        raise HTTPException(status_code=400, detail="收件人邮箱格式不正确")

    email_service = EmailService(settings)
    subject = "MSIA 邮件服务测试 - 系统连通性验证"
    body = (
        f"您好 {current.DisplayName or current.Username},\n\n"
        f"这是一封来自 MSIA 审核管理系统的邮件连通性测试邮件。\n\n"
        f"发起人: {current.DisplayName or current.Username}\n"
        f"发起时间: {now_cst().strftime('%Y-%m-%d %H:%M:%S')} (北京时间)\n\n"
        f"收到此邮件说明系统邮件服务连通正常, 问题升级通知功能可正常工作。\n\n"
        f"此邮件由 MSIA 审核管理系统自动发送, 请勿直接回复。"
    )

    ok = email_service.send_email(
        to=[payload.recipient.strip()],
        subject=subject,
        body=body,
        template_key="test_email",
        ref_type="user",
        ref_id=current.Id,
    )

    # 查询刚写入的邮件日志获取 log_id
    from app.models.email_log import EmailLog
    from app.db.session import SessionLocal

    log_id = None
    error_msg = None
    with SessionLocal() as session:
        log = (
            session.query(EmailLog)
            .filter(EmailLog.ToAddress == payload.recipient.strip())
            .order_by(EmailLog.Id.desc())
            .first()
        )
        if log:
            log_id = log.Id
            if log.Status == "failed" and log.ErrorMessage:
                error_msg = log.ErrorMessage[:500]

    return TestEmailResponse(
        ok=ok,
        message="测试邮件发送成功, 请查收" if ok else "测试邮件发送失败, 请检查 SMTP 配置与日志",
        smtp_host=settings.EMAIL_SMTP_HOST,
        smtp_port=settings.EMAIL_SMTP_PORT,
        from_address=settings.EMAIL_FROM_ADDRESS,
        log_id=log_id,
        error=error_msg,
    )
