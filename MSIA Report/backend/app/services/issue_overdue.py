"""问题逾期判定服务 (Deadline 硬边界规则)

统一逾期判定规则, 供 dashboard.py / issues.py / workbench.py / scheduler.py 调用,
保证看板统计、列表筛选、定时扫描三处口径完全一致。

规则 (按优先级从高到低):
1. 已关闭 (Status == "closed") → 不逾期
2. 已申请关闭待审批 (Status == "pending_verification") → 不逾期
   已提交关闭申请等待审核, 不视为逾期
3. Deadline 为空 → 不逾期
   (阶段实际审核完成日期未在 HRDB 填报, 即阶段评审未完成, 问题不参与逾期判定)
4. Deadline 已过 (超过 Deadline 当天, 即次日零点起) 且未关闭 → 逾期
   Deadline = 阶段实际审核完成日期 + 10 自然日 (唯一硬边界,
   原创建宽限期/计划完成日期规则已废除)

历史规则变更说明:
- 旧规则 (创建 48h 未维护计划日期逾期 / 计划完成日期过期逾期) 已于 Deadline
  规则上线时废除; PlannedCloseDate 仅作为责任人承诺日期展示, 不参与逾期判定

可配置参数 (从数据库 SystemSetting 读取):
- issue_overdue_exempt_statuses: 逾期判定中排除的状态 (默认 closed,pending_verification)
- issue_overdue_effective_from:   新规则生效时间 (北京时间, ISO 格式)
  为兼容存量问题切换, 生效时间之前不产生逾期判定; 首次读取时自动初始化为
  "次日零点" 并写库 (即新规则自次日起算逾期)

时间处理:
- 数据库中 Deadline 为 naive datetime (SQL Server sysdatetime 北京时间)
- 本服务使用 naive 北京时间 (东八区) 比较, 与 sysdatetime() 口径一致
"""
from datetime import datetime
from typing import Optional, Sequence, Tuple

from sqlalchemy import and_, text
from sqlalchemy import false as sa_false
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.issue import Issue
from app.utils.time import now_cst

# 默认值 (数据库无记录时使用)
DEFAULT_EXEMPT_STATUS = ("closed", "pending_verification")

# 新规则生效时间的 SystemSetting 键
EFFECTIVE_FROM_KEY = "issue_overdue_effective_from"


def get_naive_utc_now() -> datetime:
    """获取当前北京时间 (东八区 naive), 用于与数据库 naive datetime 比较

    注: 历史函数名保留 (避免大范围调用方改动), 语义已统一为北京时间,
    与 SQL Server sysdatetime() 口径一致。
    """
    return now_cst()


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _resolve_config(db: Optional[Session]) -> Tuple[Optional[datetime], tuple[str, ...]]:
    """从数据库读取逾期判定参数

    Returns:
        (effective_from, exempt_statuses)

    effective_from 为 None 表示不设生效限制;
    首次读取 (数据库无配置) 时初始化为"北京时间次日零点"并写库
    (存量问题切换保护: 新规则自次日起算逾期, 避免上线瞬间大量问题同时逾期)
    """
    if db is None:
        return None, DEFAULT_EXEMPT_STATUS

    from datetime import timedelta

    exempt_statuses = DEFAULT_EXEMPT_STATUS
    effective_from: Optional[datetime] = None
    try:
        from app.services.system_config_service import get_string, set_string

        exempt_str = get_string(db, "issue_overdue_exempt_statuses")
        if exempt_str:
            parts = tuple(
                s.strip() for s in exempt_str.split(",") if s.strip()
            )
            if parts:
                exempt_statuses = parts

        raw = get_string(db, EFFECTIVE_FROM_KEY)
        if raw:
            # 已有配置: 解析失败视为无限制 (不再自动初始化)
            return _parse_dt(raw), exempt_statuses

        # 无配置 → 初始化为次日零点 (写库失败不影响返回, 下次读取再补写)
        tomorrow = (now_cst() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            set_string(db, EFFECTIVE_FROM_KEY, tomorrow.strftime("%Y-%m-%d %H:%M:%S"))
            db.commit()
        except Exception:
            pass
        return tomorrow, exempt_statuses
    except Exception:
        # 数据库查询失败时回退到默认值, 保证业务不中断
        return None, DEFAULT_EXEMPT_STATUS


def _overdue_start_of(issue: Issue, effective_from: Optional[datetime]) -> Optional[datetime]:
    """计算问题的逾期起点 (不做 now 比较): 未逾期前提不满足时返回 None

    起点 = max(Deadline 次日零点, 生效时间)
    """
    if issue.Deadline is None:
        return None
    d = issue.Deadline.date()
    from datetime import datetime as _dt, timedelta as _td

    boundary = _dt(d.year, d.month, d.day) + _td(days=1)
    if effective_from is not None:
        return max(boundary, effective_from)
    return boundary


def build_overdue_filter(
    now_naive: datetime | None = None,
    db: Optional[Session] = None,
) -> Sequence:
    """构建 SQL 逾期筛选条件 (用于 ORM query.filter)

    返回一个 SQLAlchemy 表达式元组, 调用方需用 * 解包:
        db.query(Issue).filter(*build_overdue_filter())

    注意: 调用方通常需要再叠加 Issue.IsDeleted == False 等业务条件。

    Args:
        now_naive: naive 北京时间; 为 None 时自动取当前时间
        db: 数据库会话, 用于读取可配置参数

    Returns:
        SQLAlchemy 表达式元组 (可直接 * 解包到 filter)
    """
    if now_naive is None:
        now_naive = get_naive_utc_now()

    effective_from, exempt_statuses = _resolve_config(db)

    # 生效时间未到 → 全部不逾期 (永假条件)
    if effective_from is not None and now_naive < effective_from:
        return (sa_false(),)

    # 规则 4: Deadline 已过 (次日零点起) 且未关闭/未待审批
    boundary_expr = sqlfunc.dateadd(text("day"), 1, Issue.Deadline)
    return (
        ~Issue.Status.in_(exempt_statuses),  # 规则 1 + 2
        Issue.Deadline.isnot(None),  # 规则 3: 阶段评审未完成不逾期
        boundary_expr <= now_naive,  # 规则 4
    )


def build_overdue_condition(
    now_naive: datetime | None = None,
    db: Optional[Session] = None,
):
    """构建单一 SQL 布尔表达式 (用于 case() / where() 中需要单个表达式时)

    等价于 build_overdue_filter 返回条件的 AND 组合, 但不包含 IsDeleted
    (IsDeleted 由调用方在 filter 中自行添加)。
    """
    if now_naive is None:
        now_naive = get_naive_utc_now()

    effective_from, exempt_statuses = _resolve_config(db)
    if effective_from is not None and now_naive < effective_from:
        return sa_false()

    boundary_expr = sqlfunc.dateadd(text("day"), 1, Issue.Deadline)
    return and_(
        ~Issue.Status.in_(exempt_statuses),
        Issue.Deadline.isnot(None),
        boundary_expr <= now_naive,
    )


def is_issue_overdue(
    issue: Issue,
    now_naive: datetime | None = None,
    db: Optional[Session] = None,
) -> bool:
    """Python 端逾期判定 (用于 ORM 已加载的对象)

    与 build_overdue_filter 的 SQL 逻辑完全一致。

    Args:
        issue: Issue ORM 实例
        now_naive: naive 北京时间; 为 None 时自动取当前时间
        db: 数据库会话, 用于读取可配置参数

    Returns:
        True 表示逾期
    """
    if now_naive is None:
        now_naive = get_naive_utc_now()

    effective_from, exempt_statuses = _resolve_config(db)
    if effective_from is not None and now_naive < effective_from:
        return False

    # 规则 1 + 2: 已关闭/待审批关闭
    if issue.Status in exempt_statuses:
        return False

    start = _overdue_start_of(issue, effective_from)
    if start is None:
        return False
    return start <= now_naive


def get_overdue_start(
    issue: Issue,
    now_naive: datetime | None = None,
    db: Optional[Session] = None,
) -> Optional[datetime]:
    """获取问题的逾期起始时间 (naive 北京时间)

    与 is_issue_overdue 规则一致, 用于问题升级扫描计算逾期时长:
    - 已关闭 / 已申请关闭待审批 → None
    - Deadline 为空 (阶段评审未完成) → None
    - 逾期起点 = max(Deadline 次日零点, 规则生效时间)

    Returns:
        逾期起点 naive 北京时间; 未逾期返回 None
    """
    if now_naive is None:
        now_naive = get_naive_utc_now()

    effective_from, exempt_statuses = _resolve_config(db)
    if effective_from is not None and now_naive < effective_from:
        return None

    # 规则 1 + 2: 已关闭/待审批关闭 → 不逾期
    if issue.Status in exempt_statuses:
        return None

    start = _overdue_start_of(issue, effective_from)
    if start is None:
        return None
    return start if start <= now_naive else None
