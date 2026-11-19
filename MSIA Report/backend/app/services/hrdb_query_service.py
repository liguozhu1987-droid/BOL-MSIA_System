"""HRDB 只读查询服务

查询 MSIA 审核计划相关数据, 所有表位于 HRDB 数据库, 通过 pyodbc 原生连接读取。

数据源 (HRDB 表):
- [HRDB].[dbo].[CN_AME_lineDevelopment_msia_plan]          MSIA 审核计划 (主表)
- [HRDB].[dbo].[CN_AME_lineDevelopment_orderBasicInfor]   工单基本信息 (关联)
- [HRDB].[dbo].[CN_AME_lineDevelopment_projectBasicInfor] 项目基本信息 (关联)
- [HRDB].[dbo].[fine_user]                                用户表 (关联提取中文负责人名)

关联字段:
- msia_plan.orderId = orderBasicInfor.orderId = projectBasicInfor.orderId
- orderBasicInfor.userName_in_charge = fine_user.userName  (提取 realName 中括号内中文)

说明:
- 列表查询通过 LEFT JOIN 四表, 返回关联后的结构化数据
- 排除无关列 (msia1PlanDate, msia2PlanDate, msia1ActualDate, msia2ActualDate,
  updateUser, status, is_active)
- 将主键 ID 替换为行号序号 (seq), 同时保留 seqId (工单表序列号)
- 负责人列: 优先从 fine_user.realName 中提取括号内中文, 失败回退到 name_in_charge
- 分页使用 SQL Server 的 OFFSET ... FETCH NEXT ... 语法
"""
import re
from typing import Any, Dict, List, Optional

import pyodbc
from loguru import logger

from app.core.config import Settings

# HRDB 表名
_TABLE_MSIA_PLAN = "[HRDB].[dbo].[CN_AME_lineDevelopment_msia_plan]"
_TABLE_ORDER_BASIC = "[HRDB].[dbo].[CN_AME_lineDevelopment_orderBasicInfor]"
_TABLE_PROJECT_BASIC = "[HRDB].[dbo].[CN_AME_lineDevelopment_projectBasicInfor]"
_TABLE_FINE_USER = "[HRDB].[dbo].[fine_user]"

# 提取 realName 中括号内中文的正则 (如 "LF01047(路玉龙)Yulong Lu" -> "路玉龙")
_CN_IN_PARENS_RE = re.compile(r"\(([^)]*[\u4e00-\u9fff][^)]*)\)")


def _extract_cn_name(real_name: Optional[str]) -> Optional[str]:
    """从 realName 中提取括号内的中文姓名

    示例:
        "LF01047(路玉龙)Yulong Lu"  -> "路玉龙"
        "Sunny Bai (白玉)"          -> "白玉"
        "Michel van Abel"           -> None (无括号或无中文)
    """
    if not real_name:
        return None
    matches = _CN_IN_PARENS_RE.findall(real_name)
    if matches:
        # 返回第一个含中文的括号内容
        return matches[0]
    return None


class HrdbQueryService:
    """HRDB 只读查询服务 - 查询 MSIA 审核计划相关数据"""

    def __init__(self, settings: Settings):
        self._conn_str = settings.HRDB_CONNECTION_STRING

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _connect(self) -> pyodbc.Connection:
        """建立 pyodbc 连接

        设置连接超时 (login_timeout=10s) 和查询超时 (timeout=30s),
        避免 HRDB 不可达时阻塞业务请求。
        """
        conn = pyodbc.connect(self._conn_str, timeout=10)
        # 查询超时 (单位: 秒)
        conn.timeout = 30
        return conn

    @staticmethod
    def _rows_to_dicts(cursor: pyodbc.Cursor) -> List[Dict[str, Any]]:
        """将 cursor 结果集转换为 dict 列表"""
        if cursor.description is None:
            return []
        columns = [col[0] for col in cursor.description]
        return [
            {col: row[i] for i, col in enumerate(columns)}
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _row_to_dict(cursor: pyodbc.Cursor) -> Optional[Dict[str, Any]]:
        """取单行, 转换为 dict, 无结果返回 None"""
        if cursor.description is None:
            return None
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        if row is None:
            return None
        return {col: row[i] for i, col in enumerate(columns)}

    @staticmethod
    def _safe_like(value: str) -> str:
        """转义 LIKE 中的特殊字符, 包裹通配符"""
        escaped = (
            value.replace("[", "[[]")
            .replace("]", "[]]")
            .replace("_", "[_]")
            .replace("%", "[%]")
        )
        return f"%{escaped}%"

    @staticmethod
    def _resolve_owner_name(real_name: Optional[str], name_in_charge: Optional[str]) -> Optional[str]:
        """解析项目负责人中文名: 优先 realName 括号内中文, 回退 name_in_charge"""
        cn = _extract_cn_name(real_name)
        if cn:
            return cn
        if name_in_charge:
            return name_in_charge
        return None

    # ------------------------------------------------------------------
    # 列表查询: 关联四表, 选择需要的字段
    # ------------------------------------------------------------------
    def query_msia_plans(
        self,
        order_id: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        exclude_archived: bool = False,
    ) -> Dict[str, Any]:
        """查询 MSIA 审核计划列表 (关联四表)

        返回结构化字段:
        - seq: 行号序号 (基于分页内的行序, 从 1 开始)
        - seqId: 工单表序列号 (来自 orderBasicInfor.seqId)
        - orderId: 工单 ID
        - order_description: 工单描述
        - projectName: 项目名称
        - lineType: 产线类型 (来自 orderBasicInfor.lineType)
        - projectType: 项目类型 (来自 orderBasicInfor.projectType)
        - ownerName: 项目负责人中文名 (优先 realName 括号中文, 回退 name_in_charge)
        - leadUser: MSIA 负责人 (英文账号)
        - sme1, sme2: SME 成员
        - msia3PlanDate / msia3ActualDate: MSIA3 阶段计划/实际日期
        - msia4PlanDate / msia4ActualDate: MSIA4 阶段计划/实际日期
        - msia5PlanDate / msia5ActualDate: MSIA5 阶段计划/实际日期
        - plantName: 工厂名称
        - lineName: 产线名称
        - supplerName: 供应商名称
        - issueDate: 工单下发日期
        - endDate: 工单结束日期
        - updateDate: 计划更新时间

        Args:
            order_id: 工单 ID 精确过滤 (可选)
            keyword:  关键字模糊匹配 (可选)
            page:     页码, 从 1 开始
            page_size: 每页数量
            exclude_archived: 排除已完成全部阶段审核的项目 (MSIA3/4/5 实际日期
                全部已维护, 即整体进度 100%), 归档项目在"项目存档"模块展示
        """
        page = max(page, 1)
        page_size = max(page_size, 1)
        offset = (page - 1) * page_size

        result: Dict[str, Any] = {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        }

        # JOIN 关联四表, 选择需要的字段
        select_fields = [
            "P.[ID] AS planId",
            "O.[seqId] AS seqId",
            "P.[orderId] AS orderId",
            "O.[order_description] AS order_description",
            "O.[projectName] AS projectName",
            "O.[lineType] AS lineType",
            "O.[projectType] AS projectType",
            "O.[userName_in_charge] AS userName_in_charge",
            "O.[name_in_charge] AS name_in_charge",
            "F.[realName] AS realName",
            "P.[leadUser] AS leadUser",
            "P.[sme1] AS sme1",
            "P.[sme2] AS sme2",
            "P.[msia3PlanDate] AS msia3PlanDate",
            "P.[msia3ActualDate] AS msia3ActualDate",
            "P.[msia4PlanDate] AS msia4PlanDate",
            "P.[msia4ActualDate] AS msia4ActualDate",
            "P.[msia5PlanDate] AS msia5PlanDate",
            "P.[msia5ActualDate] AS msia5ActualDate",
            "PR.[plantName] AS plantName",
            "PR.[lineName] AS lineName",
            "PR.[supplerName] AS supplerName",
            "O.[issueDate] AS issueDate",
            "O.[endDate] AS endDate",
            "P.[updateDate] AS updateDate",
        ]
        select_sql = ", ".join(select_fields)

        # JOIN 子句: 主表 + 工单表 + 项目表 + 用户表
        join_sql = (
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
            f"LEFT JOIN {_TABLE_PROJECT_BASIC} AS PR ON P.[orderId] = PR.[orderId] "
            f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName]"
        )

        # WHERE 条件
        where_parts: List[str] = []
        params: List[Any] = []

        # 排除归档项目 (MSIA3/4/5 实际日期全部已维护 = 整体进度 100%)
        if exclude_archived:
            where_parts.append(
                "NOT (P.[msia3ActualDate] IS NOT NULL "
                "AND P.[msia4ActualDate] IS NOT NULL "
                "AND P.[msia5ActualDate] IS NOT NULL)"
            )

        if order_id:
            where_parts.append("(P.[orderId] = ? OR O.[orderId] = ?)")
            params.extend([order_id, order_id])

        if keyword:
            like_val = self._safe_like(keyword)
            keyword_clauses = [
                "P.[orderId] LIKE ?",
                "O.[order_description] LIKE ?",
                "O.[projectName] LIKE ?",
                "O.[lineType] LIKE ?",
                "O.[projectType] LIKE ?",
                "O.[userName_in_charge] LIKE ?",
                "O.[name_in_charge] LIKE ?",
                "F.[realName] LIKE ?",
                "P.[leadUser] LIKE ?",
                "P.[sme1] LIKE ?",
                "P.[sme2] LIKE ?",
                "PR.[plantName] LIKE ?",
                "PR.[lineName] LIKE ?",
                "PR.[supplerName] LIKE ?",
            ]
            where_parts.append("(" + " OR ".join(keyword_clauses) + ")")
            params.extend([like_val] * len(keyword_clauses))

        sql_where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # 统计总数
        count_sql = f"SELECT COUNT(*) {join_sql}{sql_where}"
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                total = int(row[0]) if row else 0
        except Exception as exc:
            logger.exception("查询 MSIA 计划总数失败: {}", exc)
            return result

        result["total"] = total
        result["total_pages"] = (total + page_size - 1) // page_size if total else 0

        # 分页查询 (按 planId 排序保证稳定分页)
        data_sql = (
            f"SELECT {select_sql} {join_sql}{sql_where} "
            f"ORDER BY P.[ID] "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        )
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(data_sql, [*params, offset, page_size])
                items = self._rows_to_dicts(cursor)

            # 后处理: 为每条记录添加 seq 行号 + ownerName 解析中文名
            for idx, item in enumerate(items, start=1):
                item["seq"] = offset + idx
                item["ownerName"] = self._resolve_owner_name(
                    item.get("realName"), item.get("name_in_charge")
                )

            result["items"] = items
        except Exception as exc:
            logger.exception("查询 MSIA 计划列表失败: {}", exc)

        return result

    def query_archived_plans(
        self,
        order_id: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询已完成全部阶段审核的归档项目列表 (项目存档模块)

        归档判定: MSIA3/4/5 实际日期全部已维护 (系统整体进度 100%。
        MSIA1/2 阶段日期在 HRDB 中未维护, 与项目详情页整体进度口径一致)

        返回字段与 query_msia_plans 一致, 额外包含 MSIA1/2 阶段计划/实际日期,
        按 MSIA5 实际完成日期倒序 (最近完成的项目在前)
        """
        page = max(page, 1)
        page_size = max(page_size, 1)
        offset = (page - 1) * page_size

        result: Dict[str, Any] = {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        }

        select_fields = [
            "P.[ID] AS planId",
            "O.[seqId] AS seqId",
            "P.[orderId] AS orderId",
            "O.[order_description] AS order_description",
            "O.[projectName] AS projectName",
            "O.[lineType] AS lineType",
            "O.[projectType] AS projectType",
            "O.[userName_in_charge] AS userName_in_charge",
            "O.[name_in_charge] AS name_in_charge",
            "F.[realName] AS realName",
            "P.[leadUser] AS leadUser",
            "P.[sme1] AS sme1",
            "P.[sme2] AS sme2",
            "P.[msia1PlanDate] AS msia1PlanDate",
            "P.[msia1ActualDate] AS msia1ActualDate",
            "P.[msia2PlanDate] AS msia2PlanDate",
            "P.[msia2ActualDate] AS msia2ActualDate",
            "P.[msia3PlanDate] AS msia3PlanDate",
            "P.[msia3ActualDate] AS msia3ActualDate",
            "P.[msia4PlanDate] AS msia4PlanDate",
            "P.[msia4ActualDate] AS msia4ActualDate",
            "P.[msia5PlanDate] AS msia5PlanDate",
            "P.[msia5ActualDate] AS msia5ActualDate",
            "PR.[plantName] AS plantName",
            "PR.[lineName] AS lineName",
            "PR.[supplerName] AS supplerName",
            "O.[issueDate] AS issueDate",
            "O.[endDate] AS endDate",
            "P.[updateDate] AS updateDate",
        ]
        select_sql = ", ".join(select_fields)

        join_sql = (
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
            f"LEFT JOIN {_TABLE_PROJECT_BASIC} AS PR ON P.[orderId] = PR.[orderId] "
            f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName]"
        )

        # WHERE: 归档条件 + 可选过滤
        where_parts: List[str] = [
            "P.[msia3ActualDate] IS NOT NULL",
            "P.[msia4ActualDate] IS NOT NULL",
            "P.[msia5ActualDate] IS NOT NULL",
        ]
        params: List[Any] = []

        if order_id:
            where_parts.append("(P.[orderId] = ? OR O.[orderId] = ?)")
            params.extend([order_id, order_id])

        if keyword:
            like_val = self._safe_like(keyword)
            keyword_clauses = [
                "P.[orderId] LIKE ?",
                "O.[order_description] LIKE ?",
                "O.[projectName] LIKE ?",
                "O.[lineType] LIKE ?",
                "O.[projectType] LIKE ?",
                "O.[userName_in_charge] LIKE ?",
                "O.[name_in_charge] LIKE ?",
                "F.[realName] LIKE ?",
                "P.[leadUser] LIKE ?",
                "P.[sme1] LIKE ?",
                "P.[sme2] LIKE ?",
                "PR.[plantName] LIKE ?",
                "PR.[lineName] LIKE ?",
                "PR.[supplerName] LIKE ?",
            ]
            where_parts.append("(" + " OR ".join(keyword_clauses) + ")")
            params.extend([like_val] * len(keyword_clauses))

        sql_where = " WHERE " + " AND ".join(where_parts)

        # 统计总数
        count_sql = f"SELECT COUNT(*) {join_sql}{sql_where}"
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                total = int(row[0]) if row else 0
        except Exception as exc:
            logger.exception("查询归档项目总数失败: {}", exc)
            return result

        result["total"] = total
        result["total_pages"] = (total + page_size - 1) // page_size if total else 0

        # 分页查询: 按 MSIA5 实际完成日期倒序 (最近完成在前), 日期相同按 planId
        data_sql = (
            f"SELECT {select_sql} {join_sql}{sql_where} "
            f"ORDER BY P.[msia5ActualDate] DESC, P.[ID] DESC "
            f"OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        )
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(data_sql, [*params, offset, page_size])
                items = self._rows_to_dicts(cursor)

            for idx, item in enumerate(items, start=1):
                item["seq"] = offset + idx
                item["ownerName"] = self._resolve_owner_name(
                    item.get("realName"), item.get("name_in_charge")
                )

            result["items"] = items
        except Exception as exc:
            logger.exception("查询归档项目列表失败: {}", exc)

        return result

    def query_archived_plan_ids(self) -> List[str]:
        """查询全部归档项目的 planId 列表 (供其他模块排除归档数据使用)

        归档判定与项目存档模块一致: MSIA3/4/5 实际日期全部已维护

        Returns:
            归档项目 planId 字符串列表 (查询失败返回空列表, 调用方需容忍降级)
        """
        sql = (
            f"SELECT P.[ID] AS planId "
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"WHERE P.[msia3ActualDate] IS NOT NULL "
            f"AND P.[msia4ActualDate] IS NOT NULL "
            f"AND P.[msia5ActualDate] IS NOT NULL"
        )
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                rows = self._rows_to_dicts(cursor)
            return [str(r.get("planId", "")).strip() for r in rows if r.get("planId")]
        except Exception as exc:
            logger.exception("查询归档项目 planId 列表失败: {}", exc)
            return []

    def query_pending_reviews(self, months_ahead: int = 1) -> List[Dict[str, Any]]:
        """查询本月和下月待评审的 MSIA 项目

        规则:
        - 日期范围: 本月1日 ~ (当前月 + months_ahead)月末
        - 待评审条件: msiaNPlanDate 在日期范围内, 且 msiaNActualDate 为空 (未完成)
        - 每个项目标注 pending_phases 列表, 含阶段代码、计划日期、距今天数
        - 按 pending_phases 中最早的计划日期排序

        Args:
            months_ahead: 向后看的月数 (1=本月+下月, 2=本月+下2月)

        Returns:
            [{planId, orderId, projectName, ownerName, leadUser, plantName, lineName,
              pending_phases: [{phase: 'MSIA1', phase_num: 1, plan_date, days_until}], ...}]
        """
        from datetime import date, timedelta
        import calendar

        today = date.today()
        # 本月1日
        range_start = today.replace(day=1)
        # 目标月末
        target_month = today.month + months_ahead
        target_year = today.year
        while target_month > 12:
            target_month -= 12
            target_year += 1
        last_day = calendar.monthrange(target_year, target_month)[1]
        range_end = date(target_year, target_month, last_day)

        # 查询所有 MSIA 计划 (含 MSIA1-5 全部日期字段)
        select_fields = [
            "P.[ID] AS planId",
            "P.[orderId] AS orderId",
            "O.[order_description] AS order_description",
            "O.[projectName] AS projectName",
            "O.[lineType] AS lineType",
            "O.[userName_in_charge] AS userName_in_charge",
            "O.[name_in_charge] AS name_in_charge",
            "O.[links_on_teams] AS links_on_teams",
            "F.[realName] AS realName",
            "P.[leadUser] AS leadUser",
            "P.[msia1PlanDate] AS msia1PlanDate",
            "P.[msia1ActualDate] AS msia1ActualDate",
            "P.[msia2PlanDate] AS msia2PlanDate",
            "P.[msia2ActualDate] AS msia2ActualDate",
            "P.[msia3PlanDate] AS msia3PlanDate",
            "P.[msia3ActualDate] AS msia3ActualDate",
            "P.[msia4PlanDate] AS msia4PlanDate",
            "P.[msia4ActualDate] AS msia4ActualDate",
            "P.[msia5PlanDate] AS msia5PlanDate",
            "P.[msia5ActualDate] AS msia5ActualDate",
            "PR.[plantName] AS plantName",
            "PR.[lineName] AS lineName",
        ]
        select_sql = ", ".join(select_fields)
        join_sql = (
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
            f"LEFT JOIN {_TABLE_PROJECT_BASIC} AS PR ON P.[orderId] = PR.[orderId] "
            f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName]"
        )
        sql = f"SELECT {select_sql} {join_sql} ORDER BY P.[ID]"

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                items = self._rows_to_dicts(cursor)
        except Exception as exc:
            logger.exception("查询待评审项目失败: {}", exc)
            return []

        # 内存中过滤: 检查每个项目的 MSIA1-5 是否有待评审阶段
        results: List[Dict[str, Any]] = []
        for item in items:
            owner_name = self._resolve_owner_name(
                item.get("realName"), item.get("name_in_charge")
            )
            pending_phases: List[Dict[str, Any]] = []

            for phase_num in range(1, 6):
                plan_date_raw = item.get(f"msia{phase_num}PlanDate")
                actual_date_raw = item.get(f"msia{phase_num}ActualDate")
                if not plan_date_raw or actual_date_raw:
                    continue

                # 解析计划日期
                plan_date: Optional[date] = None
                if isinstance(plan_date_raw, date):
                    plan_date = plan_date_raw
                elif isinstance(plan_date_raw, str):
                    try:
                        plan_date = date.fromisoformat(plan_date_raw[:10])
                    except ValueError:
                        try:
                            plan_date = date.fromisoformat(
                                plan_date_raw[:10].replace("/", "-")
                            )
                        except ValueError:
                            plan_date = None

                if plan_date is None:
                    continue

                # 检查是否在日期范围内
                if range_start <= plan_date <= range_end:
                    days_until = (plan_date - today).days
                    pending_phases.append({
                        "phase": f"MSIA{phase_num}",
                        "phase_num": phase_num,
                        "plan_date": plan_date.isoformat(),
                        "days_until": days_until,
                        "is_overdue": days_until < 0,
                    })

            if pending_phases:
                # 按计划日期排序
                pending_phases.sort(key=lambda x: x["plan_date"])
                # 项目按最早待评审阶段日期排序
                earliest_date = pending_phases[0]["plan_date"]
                results.append({
                    "planId": item.get("planId"),
                    "orderId": item.get("orderId"),
                    "projectName": item.get("projectName"),
                    "order_description": item.get("order_description"),
                    "lineType": item.get("lineType"),
                    "ownerName": owner_name,
                    "userName_in_charge": item.get("userName_in_charge"),
                    "links_on_teams": item.get("links_on_teams"),
                    "leadUser": item.get("leadUser"),
                    "plantName": item.get("plantName"),
                    "lineName": item.get("lineName"),
                    "pending_phases": pending_phases,
                    "earliest_plan_date": earliest_date,
                })

        # 按最早待评审阶段日期排序
        results.sort(key=lambda x: x["earliest_plan_date"])
        return results

    def query_order_basic_info(self, order_id: str) -> Optional[Dict[str, Any]]:
        """查询单个工单基本信息"""
        if not order_id:
            return None

        sql = f"SELECT TOP 1 * FROM {_TABLE_ORDER_BASIC} WHERE [orderId] = ?"
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [order_id])
                return self._row_to_dict(cursor)
        except Exception as exc:
            logger.exception("查询工单基本信息失败 orderId={}: {}", order_id, exc)
            return None

    def query_project_basic_info(self, order_id: str) -> Optional[Dict[str, Any]]:
        """查询项目基本信息"""
        if not order_id:
            return None

        sql = f"SELECT TOP 1 * FROM {_TABLE_PROJECT_BASIC} WHERE [orderId] = ?"
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [order_id])
                return self._row_to_dict(cursor)
        except Exception as exc:
            logger.exception("查询项目基本信息失败 orderId={}: {}", order_id, exc)
            return None

    def query_msia_plan_detail(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """查询单个 MSIA 计划详情, 含关联的工单和项目信息

        Args:
            plan_id: MSIA 计划主键 (ID 字段)

        Returns:
            dict: {
                plan: {...},               MSIA 计划详情 (已关联四表字段)
                order_basic_info: {...},   关联工单基本信息
                project_basic_info: {...}, 关联项目基本信息
            }
        """
        if not plan_id:
            return None

        # 1. 查询计划主体 + 关联工单 + 关联项目 + 关联用户
        select_fields = [
            "P.[ID] AS planId",
            "O.[seqId] AS seqId",
            "P.[orderId] AS orderId",
            "O.[order_description] AS order_description",
            "O.[projectName] AS projectName",
            "O.[lineType] AS lineType",
            "O.[projectType] AS projectType",
            "O.[userName_in_charge] AS userName_in_charge",
            "O.[name_in_charge] AS name_in_charge",
            "F.[realName] AS realName",
            "O.[issueDate] AS issueDate",
            "O.[endDate] AS endDate",
            "O.[orderStatus] AS orderStatus",
            "O.[location] AS location",
            "O.[msia_flag] AS msia_flag",
            "P.[leadUser] AS leadUser",
            "P.[sme1] AS sme1",
            "P.[sme2] AS sme2",
            "P.[msia1PlanDate] AS msia1PlanDate",
            "P.[msia1ActualDate] AS msia1ActualDate",
            "P.[msia2PlanDate] AS msia2PlanDate",
            "P.[msia2ActualDate] AS msia2ActualDate",
            "P.[msia3PlanDate] AS msia3PlanDate",
            "P.[msia3ActualDate] AS msia3ActualDate",
            "P.[msia4PlanDate] AS msia4PlanDate",
            "P.[msia4ActualDate] AS msia4ActualDate",
            "P.[msia5PlanDate] AS msia5PlanDate",
            "P.[msia5ActualDate] AS msia5ActualDate",
            "P.[updateDate] AS updateDate",
            "PR.[plantName] AS plantName",
            "PR.[lineName] AS lineName",
            "PR.[supplerName] AS supplerName",
            "PR.[developType] AS developType",
            "PR.[OTS_date] AS OTS_date",
            "PR.[PPAP_date] AS PPAP_date",
            "PR.[SOP_date] AS SOP_date",
        ]
        select_sql = ", ".join(select_fields)
        join_sql = (
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
            f"LEFT JOIN {_TABLE_PROJECT_BASIC} AS PR ON P.[orderId] = PR.[orderId] "
            f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName]"
        )

        plan_sql = f"SELECT TOP 1 {select_sql} {join_sql} WHERE P.[ID] = ?"
        plan: Optional[Dict[str, Any]] = None
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(plan_sql, [plan_id])
                plan = self._row_to_dict(cursor)
        except Exception as exc:
            logger.exception("查询 MSIA 计划详情失败 plan_id={}: {}", plan_id, exc)
            return None

        if not plan:
            return None

        # 解析项目负责人中文名
        plan["ownerName"] = self._resolve_owner_name(
            plan.get("realName"), plan.get("name_in_charge")
        )

        # 2. 从计划中提取 orderId, 查询完整的工单和项目基本信息
        order_id = str(plan.get("orderId", "")).strip() if plan.get("orderId") else ""
        order_info: Optional[Dict[str, Any]] = None
        project_info: Optional[Dict[str, Any]] = None

        if order_id:
            order_info = self.query_order_basic_info(order_id)
            project_info = self.query_project_basic_info(order_id)

        return {
            "plan": plan,
            "order_basic_info": order_info,
            "project_basic_info": project_info,
        }

    # ------------------------------------------------------------------
    # 辅助查询: 按 planId 快速获取关键字段
    # ------------------------------------------------------------------
    def query_plan_owner_info(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """按 planId 查询项目负责人和工厂信息 (用于 Issue 自动填充)

        返回:
            {
                "orderId": str,
                "userName_in_charge": str,  # 工单负责人英文账号
                "name_in_charge": str,      # 工单负责人姓名 (备用)
                "realName": str,            # fine_user.realName (含括号中文)
                "ownerName": str,            # 解析后的中文姓名
                "location": str,             # 工厂所在地 (即所属公司)
            }
        """
        if not plan_id:
            return None
        sql = (
            f"SELECT TOP 1 "
            f"O.[orderId] AS orderId, "
            f"O.[userName_in_charge] AS userName_in_charge, "
            f"O.[name_in_charge] AS name_in_charge, "
            f"F.[realName] AS realName, "
            f"O.[location] AS location "
            f"FROM {_TABLE_MSIA_PLAN} AS P "
            f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
            f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName] "
            f"WHERE P.[ID] = ?"
        )
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [plan_id])
                row = self._row_to_dict(cursor)
                if not row:
                    return None
                # 解析中文姓名
                row["ownerName"] = self._resolve_owner_name(
                    row.get("realName"), row.get("name_in_charge")
                )
                return row
        except Exception as exc:
            logger.exception("查询计划负责人信息失败 plan_id={}: {}", plan_id, exc)
            return None

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_order_id(plan: Dict[str, Any]) -> Optional[str]:
        """从计划 dict 中提取 orderId"""
        if not plan:
            return None
        for key in ("orderId", "order_id", "OrderId", "ORDERID", "orderID"):
            if key in plan and plan[key] is not None:
                return str(plan[key])
        for k, v in plan.items():
            if k and k.lower() in ("orderid", "order_id") and v is not None:
                return str(v)
        return None

    @staticmethod
    def _is_text_type(type_code: Any) -> bool:
        """判断 pyodbc 列类型是否为字符串类型"""
        try:
            name = str(type_code).lower()
        except Exception:
            return False
        return any(t in name for t in ("varchar", "char", "text"))

    # ------------------------------------------------------------------
    # 批量查询: 多个 planId -> 项目名映射 (用于综合看板关联项目)
    # ------------------------------------------------------------------
    def query_plan_project_names(self, plan_ids: List[str]) -> Dict[str, str]:
        """批量查询 planId -> projectName 映射

        Args:
            plan_ids: MSIA 计划 ID 列表 (字符串)

        Returns:
            {plan_id: project_name} 字典, 未找到的不包含在结果中
        """
        if not plan_ids:
            return {}
        # 过滤掉空值, 去重
        unique_ids = list({str(pid).strip() for pid in plan_ids if pid})
        if not unique_ids:
            return {}

        # SQL Server IN 子句参数数量上限较大, 但为安全起见分批查询 (每批 500 个)
        result: Dict[str, str] = {}
        batch_size = 500
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                for i in range(0, len(unique_ids), batch_size):
                    batch = unique_ids[i:i + batch_size]
                    placeholders = ",".join(["?"] * len(batch))
                    sql = (
                        f"SELECT P.[ID] AS planId, O.[projectName] AS projectName "
                        f"FROM {_TABLE_MSIA_PLAN} AS P "
                        f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
                        f"WHERE P.[ID] IN ({placeholders})"
                    )
                    cursor.execute(sql, batch)
                    rows = self._rows_to_dicts(cursor)
                    for row in rows:
                        pid = str(row.get("planId", "")).strip()
                        pname = row.get("projectName") or ""
                        if pid and pname:
                            result[pid] = pname
        except Exception as exc:
            logger.exception("批量查询 planId 项目名失败: {}", exc)
        return result

    # ------------------------------------------------------------------
    # 批量查询: 多个 planId -> 各阶段实际审核完成日期映射 (用于 Issue Deadline 计算)
    # ------------------------------------------------------------------
    def query_plan_phase_actual_dates(self, plan_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量查询 planId -> {msia3ActualDate, msia4ActualDate, msia5ActualDate} 映射

        用于计算问题整改完成日期 (Deadline):
        - MSIA1/MSIA2/MSIA3 的问题以 msia3ActualDate 为基准 (三阶段通常一起评审)
        - MSIA4 的问题以 msia4ActualDate 为基准
        - MSIA5 的问题以 msia5ActualDate 为基准

        Args:
            plan_ids: MSIA 计划 ID 列表 (字符串)

        Returns:
            {plan_id: {"msia3": date|None, "msia4": date|None, "msia5": date|None}}
            未找到的不包含在结果中; 日期解析失败视为 None
        """
        if not plan_ids:
            return {}
        unique_ids = list({str(pid).strip() for pid in plan_ids if pid})
        if not unique_ids:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        batch_size = 500
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                for i in range(0, len(unique_ids), batch_size):
                    batch = unique_ids[i:i + batch_size]
                    placeholders = ",".join(["?"] * len(batch))
                    sql = (
                        f"SELECT P.[ID] AS planId, "
                        f"P.[msia3ActualDate] AS msia3ActualDate, "
                        f"P.[msia4ActualDate] AS msia4ActualDate, "
                        f"P.[msia5ActualDate] AS msia5ActualDate "
                        f"FROM {_TABLE_MSIA_PLAN} AS P "
                        f"WHERE P.[ID] IN ({placeholders})"
                    )
                    cursor.execute(sql, batch)
                    rows = self._rows_to_dicts(cursor)
                    for row in rows:
                        pid = str(row.get("planId", "")).strip()
                        if not pid:
                            continue
                        result[pid] = {
                            "msia3": self._parse_date_value(row.get("msia3ActualDate")),
                            "msia4": self._parse_date_value(row.get("msia4ActualDate")),
                            "msia5": self._parse_date_value(row.get("msia5ActualDate")),
                        }
        except Exception as exc:
            logger.exception("批量查询 planId 阶段实际日期失败: {}", exc)
        return result

    @staticmethod
    def _parse_date_value(raw: Any) -> Optional["date"]:
        """解析 pyodbc 返回的日期值为 date 对象 (解析失败返回 None)"""
        from datetime import date as _date
        if raw is None:
            return None
        if isinstance(raw, _date):
            return raw
        if isinstance(raw, str):
            try:
                return _date.fromisoformat(raw[:10].replace("/", "-"))
            except ValueError:
                return None
        return None

    # ------------------------------------------------------------------
    # 批量查询: 多个 planId -> (projectName, ownerName) 映射 (用于问题筛选)
    # ------------------------------------------------------------------
    def query_plan_owner_infos(self, plan_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量查询 planId -> {projectName, ownerName, orderId, location} 映射

        关联链:
            msia_plan.orderId = orderBasicInfor.orderId
            orderBasicInfor.userName_in_charge = fine_user.userName

        Args:
            plan_ids: MSIA 计划 ID 列表 (字符串)

        Returns:
            {plan_id: {"projectName": str, "ownerName": str, "orderId": str, "location": str}}
            未找到的不包含在结果中
        """
        if not plan_ids:
            return {}
        # 过滤空值, 去重
        unique_ids = list({str(pid).strip() for pid in plan_ids if pid})
        if not unique_ids:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        batch_size = 500
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                for i in range(0, len(unique_ids), batch_size):
                    batch = unique_ids[i:i + batch_size]
                    placeholders = ",".join(["?"] * len(batch))
                    sql = (
                        f"SELECT P.[ID] AS planId, "
                        f"O.[orderId] AS orderId, "
                        f"O.[projectName] AS projectName, "
                        f"O.[userName_in_charge] AS userName_in_charge, "
                        f"O.[name_in_charge] AS name_in_charge, "
                        f"F.[realName] AS realName, "
                        f"O.[location] AS location "
                        f"FROM {_TABLE_MSIA_PLAN} AS P "
                        f"LEFT JOIN {_TABLE_ORDER_BASIC} AS O ON P.[orderId] = O.[orderId] "
                        f"LEFT JOIN {_TABLE_FINE_USER} AS F ON O.[userName_in_charge] = F.[userName] "
                        f"WHERE P.[ID] IN ({placeholders})"
                    )
                    cursor.execute(sql, batch)
                    rows = self._rows_to_dicts(cursor)
                    for row in rows:
                        pid = str(row.get("planId", "")).strip()
                        if not pid:
                            continue
                        owner_name = self._resolve_owner_name(
                            row.get("realName"), row.get("name_in_charge")
                        )
                        result[pid] = {
                            "projectName": row.get("projectName") or "",
                            "ownerName": owner_name or "",
                            "orderId": str(row.get("orderId") or ""),
                            "location": row.get("location") or "",
                        }
        except Exception as exc:
            logger.exception("批量查询 planId 负责人信息失败: {}", exc)
        return result
