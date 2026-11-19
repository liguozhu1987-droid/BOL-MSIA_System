"""APScheduler 调度器

后台任务:
- 每周一 02:00 执行用户同步 (cron: day_of_week=mon, hour=2)
  → T05-R1 #7 起 gated by HR_SYNC_ENABLED (config.ini [security] hr_sync_enabled)
- 每日 06:30 SSO 中央表派生同步 (cron: hour=6, minute=30)
  → T05-R1 #7 新增, gated by SSO_USER_SYNC_ENABLED (只更新命中用户, 不新建/不禁用)
- 每日 08:00 扫描逾期问题并发送首封提醒 (cron: hour=8), 仅首次发送并记入升级日志 Lv1,
  后续重复提醒由每小时升级扫描按 EscalationConfig 配置的周期执行
- 每日 08:30 扫描 Deadline 前 N 天仍未维护原因/措施的问题并按严重等级发送邮件提醒 (cron: hour=8, minute=30)
- 每小时 00 分扫描问题升级 (cron: minute=0), 按 EscalationConfig 配置触发 Lv1/Lv2/Lv3 邮件
- 每日 07:50 回填问题 Deadline (阶段实际审核日期后补填报后同步, cron: hour=7, minute=50)
- 每月 1 日 08:10 向责任人发送本月待审核项目提醒, 抄送审核员与管理员 (cron: day=1, hour=8, minute=10)
  → 已升级为配置驱动: 每 5 分钟检查一次, 发送日期/时刻/额外抄送人员在系统配置 monthly_reminder 模块维护,
    汇总一封发送 (收件: 审核员+管理员; 抄送: 项目负责人 + 项目所在工厂 ME 经理 + 额外抄送)
"""
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import or_

from typing import Any

from app.utils.time import now_cst


def _get_system_url(db) -> str:
    """读取系统访问地址 (数据库配置优先, 回退 config.ini)"""
    from app.core.config import settings
    from app.services.system_config_service import get_string

    return get_string(db, "system_url") or settings.effective_system_url


# 任务函数 (延迟导入以避免循环依赖)
def _run_user_sync() -> None:
    """用户同步任务 (HRDB 全量同步, T05-R1 #7 起 gated by HR_SYNC_ENABLED)"""
    from app.db.session import SessionLocal
    from app.services.user_sync import UserSyncService

    from app.core.config import settings

    if not settings.HR_SYNC_ENABLED:
        logger.info("[调度] HR 用户同步已关闭 (hr_sync_enabled=false), 跳过")
        return

    logger.info("[调度] 用户同步任务开始")
    service = UserSyncService(settings)
    with SessionLocal() as db:
        service.sync_from_hr(db)
    logger.info("[调度] 用户同步任务结束")


def _run_sso_user_sync() -> None:
    """SSO 中央表派生同步任务 (T05-R1 #7, gated by SSO_USER_SYNC_ENABLED)

    每日 06:30 从 CN_AME_SSO_User 派生更新 CN_AME_MISA_User:
    只更新命中的本地用户 (资料/状态), 不新建、不禁用未命中用户。
    """
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services.sso_user_sync import sync_from_sso_central

    if not settings.SSO_USER_SYNC_ENABLED:
        logger.info("[调度] SSO 派生同步未启用 (sso_user_sync_enabled=false), 跳过")
        return

    logger.info("[调度] SSO 中央表派生同步开始")
    try:
        with SessionLocal() as db:
            stats = sync_from_sso_central(db)
        logger.info(
            "[调度] SSO 中央表派生同步结束: 中央 {} 人, 命中 {}, 更新 {}, "
            "停用传导 {}, 恢复 {}, 本地无账号 {}",
            stats["central_read"], stats["matched"], stats["updated"],
            stats["status_disabled"], stats["status_enabled"],
            stats["skipped_no_local"],
        )
    except Exception:
        logger.exception("[调度] SSO 中央表派生同步失败")


def _scan_overdue_issues() -> None:
    """逾期问题扫描任务

    逾期判定规则 (统一调用 app.services.issue_overdue, Deadline 硬边界):
    1) 已关闭/待审批关闭 → 不逾期
    2) Deadline 为空 (阶段评审未完成) → 不逾期
    3) Deadline 已过 (次日零点起) 且未关闭 → 逾期

    邮件发送规则 (避免绕过升级配置的发送周期):
    - 仅在该问题首次逾期提醒时发送邮件 (无论出自本任务还是升级扫描 Lv1),
      发送成功后记入升级日志 (Level=1, ConfigId=NULL) 作为已提醒标记。
    - 后续重复提醒由每小时升级扫描任务按 EscalationConfig 的 Lv1 频次执行
      (如配置 48h → 逾期当日 1 封 + 之后每 48 小时 1 封),
      确保用户在升级配置中设定的发送周期真正生效, 不再每日重复发送。
    """
    from datetime import datetime
    from sqlalchemy import func as sqlfunc

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.escalation_config import EscalationLog
    from app.models.issue import Issue
    from app.models.user import User
    from app.services.email_service import EmailService
    from app.services.issue_deadline_service import build_issue_email_contexts
    from app.services.issue_overdue import build_overdue_filter, get_naive_utc_now
    from app.services.notification_service import NotificationService

    logger.info("[调度] 逾期问题扫描开始")
    email_service = EmailService(settings)
    # 统一北京时间 (东八区): 逾期判定与 SentAt 落库同口径
    now_local = now_cst()
    now_naive = now_local
    with SessionLocal() as db:
        # 通过 SQL 一次性筛出逾期问题 (与综合看板口径一致, 参数从数据库读取)
        now_query = (
            db.query(Issue)
            .filter(
                Issue.IsDeleted == False,  # noqa: E712
                *build_overdue_filter(now_naive, db),
            )
            .all()
        )
        logger.info("[调度] 候选逾期问题: {} 条", len(now_query))

        # 已收到过 Lv1 级提醒 (含每日逾期首封与升级扫描 Lv1) 的问题集合:
        # 这些问题的重复提醒由升级扫描按 EscalationConfig 周期执行, 本任务不再发邮件
        reminded_issue_ids: set[int] = {
            iid for iid, in db.query(EscalationLog.IssueId)
            .filter(EscalationLog.Level == 1)
            .distinct()
            .all()
        }

        # 批量构建邮件上下文 (项目名/阶段实际日期/Deadline, 单次 HRDB 连接)
        base_ctxs = build_issue_email_contexts(db, now_query)

        for issue in now_query:
            # 仅首次逾期提醒: 已提醒过的问题交由升级扫描按配置周期重复
            if issue.Id in reminded_issue_ids:
                continue

            owner_id = issue.OwnerUserId
            if not owner_id:
                continue
            user = db.query(User).filter(User.Id == owner_id).first()
            if not user:
                continue
            context = {
                **base_ctxs.get(issue.Id, {}),
                "status": issue.Status,
                "system_url": _get_system_url(db),
            }

            email_ok = False
            # 发送结果详情 (log_id/actual_to 等, 用于升级日志关联与记录实际收件人)
            send_result: dict = {}
            if user.Email:
                try:
                    subject, body, _ = email_service.render_template(
                        "issue_overdue", context
                    )
                    email_ok = email_service.send_with_retry(
                        to=[user.Email],
                        subject=subject,
                        body=body,
                        db=db,
                        template_key="issue_overdue",
                        ref_type="issue",
                        ref_id=issue.Id,
                        result=send_result,
                    )
                except Exception:
                    logger.exception(
                        "[调度] 逾期提醒邮件发送失败: 问题 {} 收件人 {}",
                        issue.IssueNo, user.Email,
                    )

            # 邮件发送成功 (或责任人无邮箱仅站内通知) 时登记, 后续不再重复:
            # 逾期提示 = 升级最低级别 (Lv1), 记入升级日志作为已提醒标记,
            # 重复提醒由升级扫描按 EscalationConfig 周期接管
            if email_ok or not user.Email:
                notif_service = NotificationService(db, email_service)
                notif_service.create(
                    user_id=owner_id,
                    title=f"问题已逾期: {issue.Title}",
                    content=f"问题编号 {issue.IssueNo} 已超过截止日期, 请尽快处理。",
                    notif_type="issue_overdue",
                )
                # Recipients 记录实际发送邮箱 (测试模式下为重定向后的测试邮箱)
                db.add(EscalationLog(
                    IssueId=issue.Id,
                    ConfigId=None,
                    Level=1,
                    RemindCount=1,
                    Recipients=";".join(send_result.get("actual_to") or ([user.Email] if user.Email else [])),
                    OriginalRecipients=user.Email or "",
                    EmailLogId=send_result.get("log_id"),
                    SentAt=now_local,
                ))
                db.commit()
                reminded_issue_ids.add(issue.Id)
                logger.info(
                    "[调度] 逾期提醒 (Lv1 首次) 已发送 -> {} (问题 {})",
                    user.Email or "(无邮箱, 仅站内通知)", issue.IssueNo,
                )
            else:
                logger.warning(
                    "[调度] 逾期提醒邮件发送失败, 跳过问题 {} 等待次日扫描重试",
                    issue.IssueNo,
                )
    logger.info("[调度] 逾期问题扫描结束")


def _scan_unmaintained_issues() -> None:
    """未维护问题扫描任务 (Deadline 基准)

    规则:
    - Deadline 前 N 天 (默认 3 天) 仍未维护根本原因 / 纠正措施的问题, 发送提醒邮件
    - Deadline 为空 (阶段评审未完成) 的问题不参与扫描, 与逾期判定口径一致
    - 已逾期问题不参与扫描: 逾期当日 08:00 逾期扫描与问题升级任务已单独提醒,
      避免同一问题在同一天早上先后收到"逾期通知"和"维护提醒"两封邮件
    - 按严重等级设定提醒频率:
        * H (高): 每 1 天提醒
        * M (中): 每 1 天提醒
        * L (低): 每 3 天提醒

    幂等性: 通过 EmailLog 查询同 RefId + TemplateKey 在窗口期内是否已发送, 避免重复
    """
    from datetime import timedelta

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.email_log import EmailLog
    from app.models.issue import Issue
    from app.models.user import User
    from app.services.email_service import EmailService

    logger.info("[调度] 未维护问题扫描开始")

    # 严重等级提醒频率和提醒提前量: 从数据库读取 (在 with 块内)
    # 默认值 (数据库无记录时使用)
    severity_frequency = {"H": 1, "M": 1, "L": 3}
    remind_days_before_deadline = 3

    email_service = EmailService(settings)

    sent_count = 0
    skip_count = 0
    with SessionLocal() as db:
        # 从数据库读取可配置参数 (回退到默认值)
        from app.services.system_config_service import get_int, get_string
        remind_days_before_deadline = get_int(db, "maintenance_remind_after_workdays", 3) or 3
        severity_frequency = {
            "H": get_int(db, "maintenance_severity_frequency_h", 1) or 1,
            "M": get_int(db, "maintenance_severity_frequency_m", 1) or 1,
            "L": get_int(db, "maintenance_severity_frequency_l", 3) or 3,
        }
        system_url = get_string(db, "system_url") or settings.effective_system_url

        now = now_cst()
        # Deadline 阈值: 当前时间 + N 天 (即 Deadline 在此日期之前的问题进入提醒窗口)
        deadline_threshold = now + timedelta(days=remind_days_before_deadline)

        # 查询未删除、未关闭、未逾期、Deadline 已进入提醒窗口、未维护整改方案的问题
        issues = (
            db.query(Issue)
            .filter(
                Issue.IsDeleted == False,  # noqa: E712
                Issue.Status != "closed",
                # Deadline 不为空 (阶段评审已完成), 与逾期判定口径一致
                Issue.Deadline.isnot(None),
                # Deadline 在提醒窗口内 (即将到来, 至 Deadline 当日)
                Issue.Deadline <= deadline_threshold,
                # 排除已逾期问题 (逾期边界 = Deadline 次日零点):
                # Deadline > now - 1 天 等价于 now < Deadline 次日零点
                Issue.Deadline > now - timedelta(days=1),
                # 未维护条件: 根本原因或纠正措施为空
                or_(Issue.RootCause.is_(None), Issue.RootCause == ""),
                or_(Issue.CorrectiveAction.is_(None), Issue.CorrectiveAction == ""),
            )
            .all()
        )
        logger.info("[调度] 候选未维护问题: {} 条", len(issues))

        # 批量构建邮件上下文 (项目名/阶段实际日期/Deadline, 单次 HRDB 连接)
        from app.services.issue_deadline_service import build_issue_email_contexts

        base_ctxs = build_issue_email_contexts(db, issues)

        for issue in issues:
            severity = (issue.Severity or "M").upper()
            frequency_days = severity_frequency.get(severity, 1)

            # 取负责人邮箱: 优先 OwnerUserId, 否则查 CreatedBy
            target_user = None
            if issue.OwnerUserId:
                target_user = db.query(User).filter(User.Id == issue.OwnerUserId).first()
            if not target_user and issue.CreatedBy:
                target_user = db.query(User).filter(User.Id == issue.CreatedBy).first()
            if not target_user:
                skip_count += 1
                continue

            if not target_user.Email:
                skip_count += 1
                continue

            # 幂等检查: 在 frequency_days 天内是否已发送相同提醒 (北京时间口径)
            recent_threshold = now_cst() - timedelta(days=frequency_days)
            already_sent = (
                db.query(EmailLog)
                .filter(
                    EmailLog.TemplateKey == "issue_maintenance_reminder",
                    EmailLog.RefType == "issue",
                    EmailLog.RefId == issue.Id,
                    EmailLog.ToAddress == target_user.Email,
                    EmailLog.CreatedAt >= recent_threshold,
                )
                .first()
            )
            if already_sent:
                skip_count += 1
                continue

            # 计算 Deadline 剩余天数 (负数表示已过期)
            days_to_deadline = (issue.Deadline.date() - now.date()).days if issue.Deadline else 0

            context = {
                **base_ctxs.get(issue.Id, {}),
                "owner_name": target_user.RealName or target_user.DisplayName or target_user.Username,
                "days_to_deadline": days_to_deadline,
                "system_url": system_url,
            }

            try:
                subject, body, _ = email_service.render_template("issue_maintenance_reminder", context)
            except KeyError:
                logger.warning("[调度] 邮件模板缺失: issue_maintenance_reminder")
                continue

            ok = email_service.send_email(
                to=[target_user.Email],
                subject=subject,
                body=body,
                db=db,
                template_key="issue_maintenance_reminder",
                ref_type="issue",
                ref_id=issue.Id,
            )
            if ok:
                sent_count += 1
                logger.info(
                    "[调度] 已发送提醒邮件 -> {} (问题 {} 频率 {}天)",
                    target_user.Email, issue.IssueNo, frequency_days,
                )
            else:
                skip_count += 1

    logger.info("[调度] 未维护问题扫描结束: 发送 {} 条, 跳过 {} 条", sent_count, skip_count)


def _check_monthly_review_reminder() -> None:
    """月度待审核项目提醒检查任务 (每 5 分钟检查一次是否到达发送时刻)

    发送逻辑 (汇总一封):
    - 收件人 (To): 全部启用的审核员 (lead_reviewer/reviewer) 与管理员 (admin)
    - 抄送 (Cc): 本月全部待审核项目负责人 + 项目所在工厂的 ME 经理
      (取问题升级 EscalationConfig 各工厂 L2 收件人, 无工厂专属配置时回退通配 *)
      + 系统配置的额外抄送人员 (monthly_reminder_extra_cc)
    - 邮件内容: 本月全部待审核项目清单 (项目名称 / MSIA 阶段 / 计划审核日期 /
      负责人 / CoE Teams 资料目录链接), 提示责任人上传资料

    发送时刻可配置 (系统配置 monthly_reminder 模块, 无需重启即时生效):
    - monthly_reminder_enabled: 是否启用
    - monthly_reminder_day / hour / minute: 每月几号几时几分发送

    触发规则: 当日为配置发送日 且 当前时刻不早于配置发送时刻时, 执行一次发送;
    实际触发时刻为配置时刻后的最近一次检查 (最长延迟 5 分钟)。
    幂等: 当月已成功发送过该模板 (任意收件人) 则不再发送。
    过滤口径: 禁用账户 (Status=0) 不作为收件人/抄送人。
    """
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.email_log import EmailLog
    from app.models.escalation_config import EscalationConfig
    from app.models.user import User
    from app.services.email_service import EmailService
    from app.services.hrdb_query_service import HrdbQueryService

    from app.services.system_config_service import get_bool, get_int, get_string

    now = now_cst()

    with SessionLocal() as db:
        # 读取发送时刻配置 (数据库 > 默认值)
        enabled = get_bool(db, "monthly_reminder_enabled", True)
        if not enabled:
            return
        send_day = get_int(db, "monthly_reminder_day", 1) or 1
        send_hour = get_int(db, "monthly_reminder_hour", 8) or 0
        send_minute = get_int(db, "monthly_reminder_minute", 10) or 0

        # 未到发送日/发送时刻则不触发
        if now.day != send_day:
            return
        send_at = now.replace(hour=send_hour, minute=send_minute, second=0, microsecond=0)
        if now < send_at:
            return

        month_start = now.date().replace(day=1)

        # 幂等: 当月已成功发送过该模板则跳过
        already_sent = (
            db.query(EmailLog)
            .filter(
                EmailLog.TemplateKey == "monthly_review_reminder",
                EmailLog.Status == "sent",
                EmailLog.CreatedAt >= month_start,
            )
            .first()
        )
        if already_sent:
            return

        logger.info("[调度] 月度待审核项目提醒任务触发 (配置: 每月{}日 {:02d}:{:02d})",
                    send_day, send_hour, send_minute)
        email_service = EmailService(settings)
        system_url = get_string(db, "system_url") or settings.effective_system_url

        # 查询本月待审核项目 (HRDB, months_ahead=0 即本月 1 日 ~ 月末)
        try:
            hrdb = HrdbQueryService(settings)
            plans = hrdb.query_pending_reviews(months_ahead=0)
        except Exception:
            logger.exception("[调度] 查询本月待审核项目失败, 月度提醒任务终止")
            return

        if not plans:
            logger.info("[调度] 本月无待审核项目, 月度提醒跳过")
            return
        logger.info("[调度] 本月待审核项目: {} 个", len(plans))

        # 收件人: 启用的审核员与管理员 (过滤禁用账户与空邮箱)
        to_users = (
            db.query(User)
            .filter(
                User.Role.in_(["lead_reviewer", "reviewer", "admin"]),
                User.Status == 1,  # noqa: E712
                User.IsDeleted == False,  # noqa: E712
            )
            .all()
        )
        to_list = sorted({
            (u.Email or "").strip()
            for u in to_users
            if (u.Email or "").strip()
        })
        if not to_list:
            logger.warning("[调度] 无有效收件人 (审核员/管理员均无邮箱), 月度提醒跳过")
            return

        # 项目负责人 (启用账户, 有邮箱) 映射
        owner_users: dict[str, User] = {}
        for plan in plans:
            uname = (plan.get("userName_in_charge") or "").strip()
            if not uname or uname in owner_users:
                continue
            u = (
                db.query(User)
                .filter(
                    User.Username == uname,
                    User.Status == 1,  # noqa: E712
                    User.IsDeleted == False,  # noqa: E712
                )
                .first()
            )
            if u and (u.Email or "").strip():
                owner_users[uname] = u
        cc_owners = sorted({
            u.Email.strip()
            for u in owner_users.values()
            if u.Email.strip() not in to_list
        })

        # ME 经理: 仅项目所在工厂的 L2 收件人 (专属配置优先, 回退通配 *)
        plant_codes = {
            (p.get("plantName") or "").strip().upper() for p in plans
        } - {""}
        enabled_cfgs = (
            db.query(EscalationConfig)
            .filter(EscalationConfig.IsEnabled == True)  # noqa: E712
            .all()
        )
        l2_by_plant: dict[str, set] = {}
        for c in enabled_cfgs:
            if not c.Level2Recipients:
                continue
            plant = (c.Plant or "").strip().upper()
            recips = {
                r.strip()
                for r in c.Level2Recipients.replace(";", ",").split(",")
                if r.strip()
            }
            l2_by_plant.setdefault(plant, set()).update(recips)

        cc_managers: set = set()
        for plant in plant_codes:
            cc_managers |= l2_by_plant.get(plant, set())
            if not l2_by_plant.get(plant):
                # 无工厂专属配置时回退通配 (*) 配置
                cc_managers |= l2_by_plant.get("*", set())

        # 额外抄送人员 (系统配置)
        extra_cc_str = get_string(db, "monthly_reminder_extra_cc") or ""
        extra_cc = {
            r.strip() for r in extra_cc_str.replace(";", ",").split(",") if r.strip()
        }

        # 汇总抄送列表 (排除已在收件人列表中的地址, 避免重复投递)
        cc_set = (set(cc_owners) | cc_managers | extra_cc) - set(to_list)
        cc_list = sorted(cc_set)

        # 构建项目清单行: 项目名称 / MSIA 阶段 / 计划审核日期 / 负责人 / CoE Teams 资料目录
        # CoE Teams 链接按项目 (orderId) 从 HRDB orderBasicInfor.links_on_teams 获取;
        # 链接为空时不展示该行 (不填充占位内容)
        lines = []
        for plan in plans:
            project_name = plan.get("projectName") or plan.get("orderId") or ""
            uname = (plan.get("userName_in_charge") or "").strip()
            owner = owner_users.get(uname)
            owner_name = (
                (owner.RealName or owner.DisplayName or uname) if owner else (uname or "未指定")
            )
            for ph in plan.get("pending_phases", []):
                lines.append(
                    f"- 项目: {project_name} | 阶段: {ph.get('phase', '')} "
                    f"| 计划审核日期: {ph.get('plan_date', '')} | 负责人: {owner_name}"
                )
            teams_link = (plan.get("links_on_teams") or "").strip()
            if teams_link:
                lines.append(f"  资料上传目录 (CoE Teams): {teams_link}")
        if not lines:
            return
        # 统计待审核项数 (仅阶段条目, 不含 CoE Teams 链接行)
        phase_count = sum(len(p.get("pending_phases", [])) for p in plans)

        context = {
            "year": now.year,
            "month": now.month,
            "count": phase_count,
            "project_lines": "\n".join(lines),
            "system_url": system_url,
        }
        try:
            subject, body, _ = email_service.render_template(
                "monthly_review_reminder", context
            )
        except KeyError:
            logger.warning("[调度] 邮件模板缺失: monthly_review_reminder")
            return

        ok = email_service.send_email(
            to=to_list,
            cc=cc_list,
            subject=subject,
            body=body,
            db=db,
            template_key="monthly_review_reminder",
            ref_type="monthly_plan",
        )
        if ok:
            logger.info(
                "[调度] 月度提醒汇总邮件已发送 -> 收件 {} 人, 抄送 {} 人 (本月 {} 项待审核)",
                len(to_list), len(cc_list), phase_count,
            )
        else:
            logger.warning("[调度] 月度提醒汇总邮件发送失败")


def _backfill_deadlines() -> None:
    """Deadline 回填任务

    HRDB 中阶段实际审核日期 (msia3/4/5ActualDate) 后补填报后,
    定时回填问题的空 Deadline (阶段实际日期 + 10 自然日)。
    DeadlineIsManual=True 的人工值不被覆盖。
    """
    from app.db.session import SessionLocal
    from app.services.issue_deadline_service import backfill_issue_deadlines

    logger.info("[调度] Deadline 回填任务开始")
    try:
        with SessionLocal() as db:
            filled = backfill_issue_deadlines(db)
        logger.info("[调度] Deadline 回填任务结束: 本次填充 {} 条", filled)
    except Exception:
        logger.exception("[调度] Deadline 回填任务失败")


def _fmt_escalation_hours(hours: int | None) -> str:
    """格式化升级阈值时长: 48 → '48 小时', 168 → '168 小时 (7 天)'"""
    if hours is None:
        return "未配置"
    if hours >= 24 and hours % 24 == 0:
        return f"{hours} 小时 ({hours // 24} 天)"
    if hours >= 24:
        return f"{hours} 小时 (约 {hours / 24:.1f} 天)"
    return f"{hours} 小时"


def _build_escalation_flow(cfg: Any, current_level: int) -> str:
    """构建升级流程说明文本 (邮件底部展示, 标记当前所处级别)"""

    def rep(h: int | None) -> str:
        return "未配置" if h is None else f"每 {h} 小时重复提醒"

    levels = [
        (1, f"① 逾期 {_fmt_escalation_hours(cfg.Level1Hours)} 起 → 邮件提醒责任人 ({rep(cfg.Level1Hours)})"),
        (2, f"② 逾期 {_fmt_escalation_hours(cfg.Level2Hours)} 起 → 升级至部门经理 ({rep(cfg.Level2Hours)})"),
        (3, f"③ 逾期 {_fmt_escalation_hours(cfg.Level3Hours)} 起 → 升级至 AME Director ({rep(cfg.Level3Hours)})"),
    ]
    lines = ["升级流程 (问题逾期后自动逐级升级):"]
    for lv, text in levels:
        lines.append(f"{text}{' ◀ 当前级别' if lv == current_level else ''}")
    return "\n".join(lines)


def _scan_escalations() -> dict:
    """问题升级扫描任务 (逾期后按 EscalationConfig 配置触发多级升级邮件, 并按阈值频次重复提醒)

    规则:
    - 仅对"已逾期"的问题升级 (逾期起点见 issue_overdue.get_overdue_start):
      * 逾期起点 = Deadline (阶段实际审核日期 + 10 自然日) 次日零点
      * Deadline 为空 (阶段评审未完成) → 不逾期, 不升级
      * 已关闭 / 已申请关闭待审批 → 不逾期, 不升级
    - 按问题的 工厂(OwnerCompany) + 严重等级(Severity) 查询 EscalationConfig
      无精确匹配时使用 Plant="*" 的同等级全局兜底配置
    - 各级独立触发与重复: 逾期时长达到 LevelNHours 后发送第 1 次,
      之后每隔 LevelNHours 重复发送一次 (第 n 次发送条件: 逾期时长 >= n * LevelNHours)
      例: 配置 (48, 168, 336) → Lv1 责任人每 48h 一次, Lv2 部门经理每 168h 一次,
      Lv3 AME Director 每 336h 一次, 逾期未处理期间持续提醒

    升级级别:
    - Level 1: 发送给责任人 (Level1Recipients 为空则用责任人邮箱)
    - Level 2: 升级给部门经理 (Level2Recipients)
    - Level 3: 升级给 AME Director (Level3Recipients)

    返回:
        {"scanned": N, "sent": N, "skipped": N}
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import and_, func as sqlfunc

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.escalation_config import EscalationConfig, EscalationLog
    from app.models.issue import Issue
    from app.models.user import User
    from app.services.email_service import EmailService
    from app.services.issue_overdue import get_overdue_start

    logger.info("[调度] 问题升级扫描开始")
    result = {"scanned": 0, "sent": 0, "skipped": 0}

    # 统一北京时间 (东八区, naive): 逾期计算与 SentAt 落库同一口径,
    # 与逾期起点字段 (CreatedAt/PlannedCloseDate, sysdatetime 北京时间) 一致
    now_naive = now_cst()
    now_local = now_naive
    email_service = EmailService(settings)

    with SessionLocal() as db:
        # 从数据库读取 system_url (回退到 config.ini)
        from app.services.system_config_service import get_string
        system_url = get_string(db, "system_url") or settings.effective_system_url
        # 加载所有启用的升级配置, 构建查找索引: (Plant, Severity) -> config
        configs = (
            db.query(EscalationConfig)
            .filter(EscalationConfig.IsEnabled == True)  # noqa: E712
            .all()
        )
        # 精确匹配 (Plant, Severity) 和兜底 (*, Severity)
        exact_map: dict[tuple[str, str], EscalationConfig] = {}
        fallback_map: dict[str, EscalationConfig] = {}
        for cfg in configs:
            exact_map[(cfg.Plant, cfg.Severity)] = cfg
            # 全局兜底: 仅 Plant="*" 的配置可作为兜底,
            # 避免某等级只有具体工厂配置时其他工厂误用别厂规则
            if cfg.Plant == "*" and cfg.Severity not in fallback_map:
                fallback_map[cfg.Severity] = cfg

        def resolve_config(plant: str | None, severity: str) -> EscalationConfig | None:
            if plant:
                cfg = exact_map.get((plant, severity))
                if cfg:
                    return cfg
            return fallback_map.get(severity)

        # 预加载各问题各级别已发送次数: {(IssueId, Level): count}
        # 仅统计升级扫描自身发送的记录 (ConfigId 非空),
        # 逾期提醒日志 (ConfigId 为空的 Lv1) 不参与升级重复节奏计算
        sent_count_rows = (
            db.query(
                EscalationLog.IssueId,
                EscalationLog.Level,
                sqlfunc.count(EscalationLog.Id),
            )
            .filter(EscalationLog.ConfigId.isnot(None))
            .group_by(EscalationLog.IssueId, EscalationLog.Level)
            .all()
        )
        sent_counts: dict[tuple[int, int], int] = {
            (iid, lvl): cnt for iid, lvl, cnt in sent_count_rows
        }

        # 查询未删除、未关闭的问题 (是否逾期由 get_overdue_start 判定)
        issues = (
            db.query(Issue)
            .filter(
                Issue.IsDeleted == False,  # noqa: E712
                Issue.Status != "closed",
            )
            .all()
        )
        result["scanned"] = len(issues)

        # 批量构建邮件统一上下文 (项目名/阶段实际日期/Deadline, 单次 HRDB 连接)
        from app.services.issue_deadline_service import build_issue_email_contexts

        base_ctxs = build_issue_email_contexts(db, issues)

        for issue in issues:
            severity = (issue.Severity or "M").upper()
            plant = issue.OwnerCompany or None
            cfg = resolve_config(plant, severity)
            if not cfg:
                result["skipped"] += 1
                continue

            # 逾期起点: 未逾期 (含待审批关闭) 不升级
            overdue_start = get_overdue_start(issue, now_naive, db)
            if overdue_start is None:
                result["skipped"] += 1
                continue

            # 逾期时长 (小时)
            overdue_hours = int((now_naive - overdue_start).total_seconds() // 3600)
            overdue_days = overdue_hours // 24

            # 各级独立判断: 第 n 次发送条件 overdue_hours >= n * threshold
            thresholds = {
                1: cfg.Level1Hours,
                2: cfg.Level2Hours,
                3: cfg.Level3Hours,
            }

            for level, threshold in thresholds.items():
                already = sent_counts.get((issue.Id, level), 0)
                next_due = (already + 1) * threshold
                if overdue_hours < next_due:
                    continue  # 未到该级别本次提醒时间

                # 获取收件人
                rec_str = ""
                if level == 1:
                    rec_str = cfg.Level1Recipients or ""
                elif level == 2:
                    rec_str = cfg.Level2Recipients or ""
                else:
                    rec_str = cfg.Level3Recipients or ""

                recipients: list[str] = []
                if rec_str:
                    recipients = [
                        r.strip() for r in rec_str.replace(";", ",").split(",") if r.strip()
                    ]

                # Level1 若无配置收件人, 使用责任人邮箱
                owner_user = None
                if level == 1 and not recipients:
                    if issue.OwnerUserId:
                        owner_user = db.query(User).filter(User.Id == issue.OwnerUserId).first()
                    if not owner_user and issue.OwnerUserName:
                        owner_user = (
                            db.query(User)
                            .filter(User.Username == issue.OwnerUserName)
                            .first()
                        )
                    if owner_user and owner_user.Email:
                        recipients = [owner_user.Email]

                if not recipients:
                    continue

                # 责任人姓名
                owner_name = issue.OwnerName or ""
                if not owner_name:
                    if owner_user is None:
                        if issue.OwnerUserId:
                            owner_user = (
                                db.query(User)
                                .filter(User.Id == issue.OwnerUserId)
                                .first()
                            )
                        if not owner_user and issue.OwnerUserName:
                            owner_user = (
                                db.query(User)
                                .filter(User.Username == issue.OwnerUserName)
                                .first()
                            )
                    if owner_user:
                        owner_name = (
                            owner_user.RealName
                            or owner_user.DisplayName
                            or owner_user.Username
                        )

                remind_count = already + 1
                template_key = f"escalation_level{level}"
                base_ctx = base_ctxs.get(issue.Id, {})
                context = {
                    **base_ctx,
                    "project_name": base_ctx.get("project_name") or "未关联项目",
                    "owner_name": owner_name or "责任人",
                    "plant": plant or "未指定",
                    "planned_close_date": (
                        issue.PlannedCloseDate.strftime("%Y-%m-%d")
                        if issue.PlannedCloseDate else "未维护"
                    ),
                    "overdue_hours": overdue_hours,
                    "overdue_days": overdue_days,
                    "remind_count": remind_count,
                    "remind_interval_hours": threshold,
                    "escalation_flow": _build_escalation_flow(cfg, level),
                    "system_url": system_url,
                }

                try:
                    subject, body, _ = email_service.render_template(template_key, context)
                except KeyError:
                    logger.warning("[调度] 升级邮件模板缺失: {}", template_key)
                    continue

                # 发送结果详情 (log_id/actual_to 等, 用于升级日志关联与记录实际收件人)
                send_result: dict = {}
                ok = email_service.send_email(
                    to=recipients,
                    subject=subject,
                    body=body,
                    db=db,
                    template_key=template_key,
                    ref_type="issue",
                    ref_id=issue.Id,
                    result=send_result,
                )

                if ok:
                    # 记录升级日志 (SentAt 用本地时间, 与系统其他时间字段口径一致)
                    # Recipients 记录实际发送邮箱 (测试模式下为重定向后的测试邮箱),
                    # OriginalRecipients 保留策略原始收件人, EmailLogId 关联邮件日志
                    log_entry = EscalationLog(
                        IssueId=issue.Id,
                        ConfigId=cfg.Id,
                        Level=level,
                        RemindCount=remind_count,
                        Recipients=";".join(send_result.get("actual_to") or recipients),
                        OriginalRecipients=";".join(recipients),
                        EmailLogId=send_result.get("log_id"),
                        SentAt=now_local,
                    )
                    db.add(log_entry)
                    db.commit()
                    # 更新内存计数, 防止同轮重复
                    sent_counts[(issue.Id, level)] = remind_count
                    result["sent"] += 1
                    logger.info(
                        "[调度] 升级邮件 Lv{} 第 {} 次已发送 -> {} (问题 {} 逾期 {}h 阈值 {}h)",
                        level, remind_count, recipients, issue.IssueNo,
                        overdue_hours, threshold,
                    )
                else:
                    result["skipped"] += 1

    logger.info(
        "[调度] 问题升级扫描结束: 扫描 {} 发送 {} 跳过 {}",
        result["scanned"], result["sent"], result["skipped"],
    )
    return result


# 调度器实例 (全局单例)
jobstores = {"default": MemoryJobStore()}
executors = {"default": ThreadPoolExecutor(5)}
job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 600}

scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone="Asia/Shanghai",
)


def start_scheduler() -> None:
    """启动调度器并注册定时任务

    幂等: 已启动则跳过。
    """
    if scheduler.running:
        logger.warning("调度器已在运行, 跳过重复启动")
        return

    # 每周一 02:00 用户同步 (T05-R1 #7 起 gated by HR_SYNC_ENABLED,
    # SSO 派生同步接管后置 hr_sync_enabled=false 即静默跳过)
    scheduler.add_job(
        _run_user_sync,
        trigger=CronTrigger(day_of_week="mon", hour=2, minute=0),
        id="user_sync_weekly",
        name="每周用户同步",
        replace_existing=True,
    )

    # 每日 06:30 SSO 中央表派生同步 (T05-R1 #7, gated by SSO_USER_SYNC_ENABLED:
    # 只更新命中用户, 不新建/不禁用未命中 —— 详见 app/services/sso_user_sync.py)
    scheduler.add_job(
        _run_sso_user_sync,
        trigger=CronTrigger(hour=6, minute=30),
        id="sso_user_sync_daily",
        name="每日SSO中央表派生同步",
        replace_existing=True,
    )

    # 每日 07:50 回填问题 Deadline (HRDB 阶段实际日期后补填报后同步)
    scheduler.add_job(
        _backfill_deadlines,
        trigger=CronTrigger(hour=7, minute=50),
        id="deadline_backfill_daily",
        name="每日问题Deadline回填",
        replace_existing=True,
    )

    # 每日 08:00 逾期扫描
    scheduler.add_job(
        _scan_overdue_issues,
        trigger=CronTrigger(hour=8, minute=0),
        id="overdue_scan_daily",
        name="每日逾期问题扫描",
        replace_existing=True,
    )

    # 每日 08:30 未维护问题邮件提醒 (闭环管理: 2 工作日内须维护原因/措施/计划日期)
    scheduler.add_job(
        _scan_unmaintained_issues,
        trigger=CronTrigger(hour=8, minute=30),
        id="unmaintained_scan_daily",
        name="每日未维护问题邮件提醒",
        replace_existing=True,
    )

    # 每小时 00 分扫描问题升级 (按 EscalationConfig 触发 Lv1/Lv2/Lv3)
    scheduler.add_job(
        _scan_escalations,
        trigger=CronTrigger(minute=0),
        id="escalation_scan_hourly",
        name="每小时问题升级扫描",
        replace_existing=True,
    )

    # 每 5 分钟检查是否到达月度提醒配置的发送时刻 (日期/时刻可在系统配置中修改, 即时生效)
    scheduler.add_job(
        _check_monthly_review_reminder,
        trigger=CronTrigger(minute="*/5"),
        id="monthly_review_reminder",
        name="每月待审核项目提醒 (配置驱动)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "APScheduler 已启动, 注册任务: user_sync_weekly, sso_user_sync_daily, "
        "deadline_backfill_daily, overdue_scan_daily, unmaintained_scan_daily, "
        "escalation_scan_hourly, monthly_review_reminder"
    )


def shutdown_scheduler() -> None:
    """关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler 已关闭")
