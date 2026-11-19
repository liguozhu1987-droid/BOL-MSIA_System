# -*- coding: utf-8 -*-
"""人员状态回写调度器 (R8 核心, 方案文档 6.2)

每小时调用 sync_sso_status 命令, 把 SSO 中央表 (CN_AME) 的停用状态传导到
本地 Employee (并清除 AuthToken), 双轨期即启用 —— 本地 Token 通道的离职缺口
从"最长 30 天"压到"<=1 小时"。

使用说明:
  - 每 SSO_STATUS_SYNC_HOURS 小时 (默认 1) 自动执行 sync_sso_status 命令
  - 仅在 settings.SCHEDULER_ENABLED=True 且 SSO_STATUS_SYNC_ENABLED=True 时启动
  - DEBUG 模式默认不启动 (开发环境避免误操作数据库),
    可通过环境变量 BOL_ENABLE_SCHEDULER=1 强制启动
  - 防止重复启动 (使用模块级变量 _scheduler)
  - apscheduler 未安装时给出提示但不影响 Django 启动

依赖:
  pip install apscheduler
"""
import logging

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    """启动 SSO 员工状态回写调度器

    - 检查 settings.SSO_STATUS_SYNC_ENABLED / SCHEDULER_ENABLED, 未启用时跳过
    - 检查 _scheduler 是否已存在, 防止重复启动
    - 注册周期性 sync_sso_status 任务 (默认每小时)
    - apscheduler 未安装时降级为日志告警, 不抛异常
    """
    global _scheduler

    if not getattr(settings, 'SSO_STATUS_SYNC_ENABLED', True):
        logger.info('SSO 状态回写已禁用 (SSO_STATUS_SYNC_ENABLED=False)')
        return

    if not getattr(settings, 'SCHEDULER_ENABLED', False):
        logger.info('定时任务已禁用 (SCHEDULER_ENABLED=False)')
        return

    if _scheduler is not None:
        logger.info('调度器已在运行')
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning('apscheduler 未安装, SSO 状态回写无法启动。请执行: pip install apscheduler')
        return

    _scheduler = BackgroundScheduler()

    try:
        hours = max(1, int(getattr(settings, 'SSO_STATUS_SYNC_HOURS', 1)))
    except (TypeError, ValueError):
        hours = 1
    _scheduler.add_job(
        _sync_sso_status,
        trigger=IntervalTrigger(hours=hours),
        id='sso_status_sync',
        name='SSO 员工状态回写',
        replace_existing=True,
        misfire_grace_time=1800,  # 如果错过, 30 分钟内仍可执行
    )

    _scheduler.start()
    logger.info('SSO 状态回写调度器已启动, 每 %d 小时执行一次', hours)


def _sync_sso_status():
    """执行状态回写 (被定时任务调用)

    异常被捕获并记录日志, 避免调度器因任务异常而退出。
    """
    try:
        call_command('sync_sso_status')
    except Exception as e:
        logger.error('SSO 员工状态回写失败: %s', e, exc_info=True)


def shutdown_scheduler():
    """关闭调度器

    在 Django 关闭时调用, 释放调度器资源。
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info('SSO 状态回写调度器已关闭')
