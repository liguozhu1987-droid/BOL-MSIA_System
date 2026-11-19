"""问题整改完成日期 (Deadline) 服务

职责:
1. Deadline 计算: 阶段实际审核完成日期 (HRDB msia_plan) + 10 自然日
   - MSIA1/MSIA2/MSIA3 → msia3ActualDate (三阶段通常一起评审)
   - MSIA4            → msia4ActualDate
   - MSIA5            → msia5ActualDate
2. Deadline 回填: 阶段实际日期在 HRDB 后补填报后, 定时任务回填问题的空 Deadline
   (DeadlineIsManual=True 的人工值不被覆盖)
3. 邮件统一上下文: 构建"问题编号/评审项目/评审阶段/问题项/问题描述/严重等级/
   评审日期/整改完成日期"标准信息块, 供所有问题类邮件模板使用

时间口径: 北京时间 (东八区, naive), 与数据库 sysdatetime() 一致
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.check_item import CheckItem
from app.models.issue import Issue
from app.services.hrdb_query_service import HrdbQueryService

# 阶段代码 → HRDB 实际日期字段键 (MSIA1/2/3 共用 msia3ActualDate)
PHASE_ACTUAL_KEY: dict[str, str] = {
    "MSIA1": "msia3",
    "MSIA2": "msia3",
    "MSIA3": "msia3",
    "MSIA4": "msia4",
    "MSIA5": "msia5",
}

# Deadline = 阶段实际审核完成日期 + DEADLINE_PLUS_DAYS 个自然日
DEADLINE_PLUS_DAYS = 10

# ItemNo 形如 "2.12" → 问题项显示 "MSIA2-12"
_ITEMNO_RE = re.compile(r"^\d+\.(.+)$")


def compute_deadline(actual: date) -> datetime:
    """由阶段实际审核完成日期计算 Deadline (实际日期 + 10 自然日, 零点)"""
    return datetime(actual.year, actual.month, actual.day) + timedelta(days=DEADLINE_PLUS_DAYS)


def overdue_boundary(deadline: datetime) -> datetime:
    """逾期边界: Deadline 次日零点 (Deadline 当天全天有效, 次日起视为逾期)"""
    d = deadline.date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day)


def format_item_display(phase_code: Optional[str], item_no: Optional[str]) -> str:
    """问题项显示格式: ItemNo "2.12" + PhaseCode "MSIA2" → "MSIA2-12"

    ItemNo 不含阶段前缀点号时直接拼接 "MSIA2-{item_no}"; PhaseCode 缺失时原样返回 ItemNo
    """
    phase = (phase_code or "").strip()
    no = (item_no or "").strip()
    if not phase:
        return no
    if not no:
        return phase
    m = _ITEMNO_RE.match(no)
    if m:
        return f"{phase}-{m.group(1)}"
    return f"{phase}-{no}"


def backfill_issue_deadlines(
    db: Session,
    issues: Optional[list[Issue]] = None,
) -> int:
    """回填问题的空 Deadline (按 HRDB 阶段实际日期 + 10 自然日)

    规则:
    - 仅处理 Deadline 为空 且 DeadlineIsManual=False 的问题
      (人工修改过的问题不被覆盖; 人工清空视为"不参与逾期", 同样不覆盖)
    - 阶段实际日期未填报 / PlanId 缺失 / 阶段代码无法识别 → 跳过 (保持空)

    Args:
        db: 数据库会话
        issues: 指定问题列表 (为 None 时查询所有待回填问题)

    Returns:
        本次回填的问题数量
    """
    if issues is None:
        issues = (
            db.query(Issue)
            .filter(
                Issue.IsDeleted == False,  # noqa: E712
                Issue.Deadline.is_(None),
                Issue.DeadlineIsManual == False,  # noqa: E712
            )
            .all()
        )

    pending = [
        it for it in issues
        if it.Deadline is None
        and not it.DeadlineIsManual
        and it.PlanId
        and (it.PhaseCode or "").upper() in PHASE_ACTUAL_KEY
    ]
    if not pending:
        return 0

    plan_ids = sorted({str(it.PlanId).strip() for it in pending})
    try:
        service = HrdbQueryService(settings)
        actual_map = service.query_plan_phase_actual_dates(plan_ids)
    except Exception as exc:
        logger.warning("回填 Deadline 查询 HRDB 阶段实际日期失败: {}", exc)
        return 0

    filled = 0
    for it in pending:
        info = actual_map.get(str(it.PlanId).strip())
        if not info:
            continue
        actual = info.get(PHASE_ACTUAL_KEY[(it.PhaseCode or "").upper()])
        if actual is None:
            continue
        it.Deadline = compute_deadline(actual)
        filled += 1

    if filled:
        db.commit()
        logger.info("Deadline 回填完成: 本次填充 {} 条", filled)
    return filled


def _fmt_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalize_item_no_key(phase_code: Optional[str], item_no: Optional[str]) -> str:
    """规范化 (阶段, 编号) 为统一匹配键: "MSIA2-10"

    兼容两种存储格式: Issue.ItemNo "MSIA2-10" / CheckItem.ItemNo "2.10"
    均归一为 "{PhaseCode}-{数字}" 形式 (大小写不敏感, 数字部分取末段)。
    """
    phase = (phase_code or "").strip().upper()
    no = (item_no or "").strip()
    if not no:
        return phase
    # 去掉阶段前缀: "MSIA2-10" → "10", "MSIA2.10" → "10"
    if phase and no.upper().startswith(phase + "-"):
        no = no[len(phase) + 1:]
    elif phase and no.upper().startswith(phase + "."):
        no = no[len(phase) + 1:]
    # 去掉点号前缀: "2.10" → "10"
    m = _ITEMNO_RE.match(no)
    if m:
        no = m.group(1)
    return f"{phase}-{no}" if phase else no


def _load_check_item_names(db: Session, issues: list[Issue]) -> dict[int, Optional[str]]:
    """批量查询问题对应检查项的内容 (Name)

    优先按 Issue.ItemId 关联 CheckItem.Id; 未关联/失效的问题按
    规范化 (PhaseCode, ItemNo) 键匹配。返回 {Issue.Id: 检查项内容或 None}。
    """
    name_by_issue: dict[int, Optional[str]] = {}

    item_ids = {it.ItemId for it in issues if getattr(it, "ItemId", None)}
    id_to_name: dict[int, str] = {}
    if item_ids:
        rows = (
            db.query(CheckItem.Id, CheckItem.Name)
            .filter(CheckItem.Id.in_(item_ids))
            .all()
        )
        id_to_name = {r[0]: r[1] for r in rows}

    # 未命中 ItemId 的问题, 按 (阶段, 编号) 键兜底匹配
    unmatched = [
        it for it in issues
        if not it.ItemId or it.ItemId not in id_to_name
    ]
    key_to_name: dict[str, str] = {}
    if unmatched:
        phases = {(it.PhaseCode or "").strip() for it in unmatched if (it.PhaseCode or "").strip()}
        if phases:
            rows = (
                db.query(CheckItem.PhaseCode, CheckItem.ItemNo, CheckItem.Name)
                .filter(CheckItem.PhaseCode.in_(phases))
                .all()
            )
            key_to_name = {
                _normalize_item_no_key(r[0], r[1]): (r[2] or "").strip() for r in rows
            }

    for it in issues:
        name: Optional[str] = None
        if it.ItemId and it.ItemId in id_to_name:
            name = id_to_name[it.ItemId]
        if not name:
            key = _normalize_item_no_key(it.PhaseCode, it.ItemNo)
            name = key_to_name.get(key)
        name_by_issue[it.Id] = (name or "").strip() or None
    return name_by_issue


def build_issue_email_contexts(db: Session, issues: Iterable[Issue]) -> dict[int, dict]:
    """批量构建问题邮件统一上下文 (单次 HRDB 连接)

    返回 {Issue.Id: context}, context 包含:
    - issue_no / project_name / phase_code / item_display / title / severity
    - review_date (阶段实际审核完成日期, HRDB 填报值)
    - deadline (整改完成日期)
    - item_no / created_at (兼容旧模板)

    item_display 为检查项具体内容 (CheckItem.Name), 便于责任人直接识别
    问题对应的审核检查项; 检查项缺失时回退为 "阶段-编号" 显示格式。
    """
    issues = list(issues)
    check_item_names = _load_check_item_names(db, issues)
    plan_ids = sorted({
        str(it.PlanId).strip()
        for it in issues
        if getattr(it, "PlanId", None) not in (None, "")
    })

    name_map: dict[str, str] = {}
    actual_map: dict[str, dict[str, Any]] = {}
    if plan_ids:
        try:
            service = HrdbQueryService(settings)
            infos = service.query_plan_owner_infos(plan_ids)
            name_map = {pid: info.get("projectName", "") for pid, info in infos.items()}
            actual_map = service.query_plan_phase_actual_dates(plan_ids)
        except Exception as exc:
            logger.warning("构建问题邮件上下文查询 HRDB 失败: {}", exc)

    contexts: dict[int, dict] = {}
    for it in issues:
        pid = str(it.PlanId).strip() if it.PlanId else ""
        project_name = name_map.get(pid, "") if pid else ""
        review_date = ""
        if pid and actual_map.get(pid):
            key = PHASE_ACTUAL_KEY.get((it.PhaseCode or "").upper())
            if key:
                review_date = _fmt_date(actual_map[pid].get(key))
        contexts[it.Id] = {
            "issue_no": it.IssueNo or "",
            "project_name": project_name,
            "phase_code": it.PhaseCode or "",
            "item_display": check_item_names.get(it.Id) or format_item_display(it.PhaseCode, it.ItemNo),
            "item_no": it.ItemNo or "",
            "title": it.Title or "",
            "severity": it.Severity or "M",
            "review_date": review_date,
            "deadline": _fmt_date(it.Deadline),
            "created_at": it.CreatedAt.strftime("%Y-%m-%d %H:%M") if it.CreatedAt else "",
        }
    return contexts


def build_issue_email_context(db: Session, issue: Issue) -> dict:
    """构建单个问题的邮件统一上下文"""
    return build_issue_email_contexts(db, [issue]).get(issue.Id, {})
