"""路由聚合

将所有子路由挂载到统一前缀下。
"""
from fastapi import APIRouter

from app.api import (
    admin,
    archive,
    attachments,
    auth,
    check_items,
    dashboard,
    escalation,
    historic_scores,
    issues,
    msia_plan,
    notifications,
    phase_reports,
    phase_review_items,
    phases,
    projects,
    reports,
    reviews,
    system_settings,
    users,
    workbench,
)

api_router = APIRouter()

# 各子路由内部已声明 /api/xxx 前缀
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(phases.router)
api_router.include_router(check_items.router)
api_router.include_router(phase_review_items.router)
api_router.include_router(reviews.router)
api_router.include_router(issues.router)
api_router.include_router(reports.router)
api_router.include_router(phase_reports.router)
api_router.include_router(notifications.router)
api_router.include_router(attachments.router)
api_router.include_router(admin.router)
api_router.include_router(msia_plan.router)
api_router.include_router(archive.router)
api_router.include_router(workbench.router)
api_router.include_router(escalation.router)
api_router.include_router(dashboard.router)
api_router.include_router(historic_scores.router)
api_router.include_router(system_settings.router)

__all__ = ["api_router"]
