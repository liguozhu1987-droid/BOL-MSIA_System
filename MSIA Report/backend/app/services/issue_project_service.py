"""问题项目信息注入服务

为问题列表批量注入项目名称 (来自 HRDB projectName, 通过 PlanId 关联),
供问题管理 (issues.py) 与工作空间 (workbench.py) 共用, 避免重复实现。
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.issue import Issue
from app.services.hrdb_query_service import HrdbQueryService


def attach_project_names(db: Session, issues: list[Any]) -> None:
    """为问题对象列表注入 ProjectName 属性 (原地修改)

    - 按 distinct PlanId 批量查询 HRDB, 一次连接获取全部项目名称
    - PlanId 为空 / HRDB 查询失败 → ProjectName 置空字符串 (遵循空值不兜底原则)
    """
    plan_ids = {
        str(it.PlanId).strip()
        for it in issues
        if getattr(it, "PlanId", None) not in (None, "")
    }
    name_map: dict[str, str] = {}
    if plan_ids:
        try:
            service = HrdbQueryService(settings)
            infos = service.query_plan_owner_infos(sorted(plan_ids))
            name_map = {pid: info.get("projectName", "") for pid, info in infos.items()}
        except Exception as exc:
            logger.warning("问题列表注入项目名称失败 (HRDB): {}", exc)

    for it in issues:
        pid = str(it.PlanId).strip() if it.PlanId else ""
        it.ProjectName = name_map.get(pid, "") if pid else ""
