# -*- coding: utf-8 -*-
"""定时任务调度器

使用 APScheduler 在 Django 启动时注册定时任务，定期发送改善机会分析周报。

使用说明：
  - 每周二中午 12:00 自动执行 send_improvement_report 命令
  - 仅在 settings.SCHEDULER_ENABLED = True 时启动
  - 防止重复启动（使用模块级变量 _scheduler）
  - apscheduler 未安装时给出提示但不影响 Django 启动

依赖：
  pip install apscheduler
"""
import logging
from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    """启动定时任务调度器

    - 检查 settings.SCHEDULER_ENABLED，未启用时跳过
    - 检查 _scheduler 是否已存在，防止重复启动
    - 注册每周二 12:00 的周报发送任务
    - apscheduler 未安装时降级为日志告警，不抛异常
    """
    global _scheduler

    if not getattr(settings, 'SCHEDULER_ENABLED', False):
        logger.info('定时任务已禁用 (SCHEDULER_ENABLED=False)')
        return

    if _scheduler is not None:
        logger.info('调度器已在运行')
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning('apscheduler 未安装，定时任务无法启动。请执行: pip install apscheduler')
        return

    _scheduler = BackgroundScheduler()

    # 每周二中午 12:00 发送改善机会分析周报
    _scheduler.add_job(
        _send_weekly_report,
        trigger=CronTrigger(day_of_week='tue', hour=12, minute=0),
        id='weekly_improvement_report',
        name='改善机会分析周报',
        replace_existing=True,
        misfire_grace_time=3600,  # 如果错过，1小时内仍可执行
    )

    _scheduler.start()
    logger.info('定时任务调度器已启动，每周二 12:00 发送改善机会分析周报')


def _send_weekly_report():
    """执行周报发送（被定时任务调用）

    异常被捕获并记录日志，避免调度器因任务异常而退出。
    """
    try:
        call_command('send_improvement_report')
    except Exception as e:
        logger.error(f'发送改善机会分析周报失败: {e}', exc_info=True)


def shutdown_scheduler():
    """关闭调度器

    在 Django 关闭时调用，释放调度器资源。
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info('定时任务调度器已关闭')
