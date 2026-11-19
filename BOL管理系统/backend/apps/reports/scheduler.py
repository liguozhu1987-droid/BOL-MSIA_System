# -*- coding: utf-8 -*-
"""报告定时生成调度器

季度报告：每季首日（1/4/7/10 月 1 日）02:00 生成上一完整季度报告
年度报告：每年 1 月 1 日 03:00 生成上一年度报告

- 仅在 settings.SCHEDULER_ENABLED 开启时启动（沿用 analytics 调度器约定）
- 生成失败仅记录日志，不影响调度器运行
- 生成人与「系统自动」，同周期重复执行时全量替换
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler():
    global _scheduler

    if not getattr(settings, 'SCHEDULER_ENABLED', False):
        logger.info('报告定时生成已禁用 (SCHEDULER_ENABLED=False)')
        return

    if _scheduler is not None:
        logger.info('报告调度器已在运行')
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning('apscheduler 未安装，报告定时生成无法启动')
        return

    _scheduler = BackgroundScheduler()

    # 每季首日 02:00 生成上一完整季度的季度报告
    _scheduler.add_job(
        _gen_quarterly,
        trigger=CronTrigger(month='1,4,7,10', day=1, hour=2, minute=0),
        id='quarterly_report',
        name='BOL 季度报告自动生成',
        replace_existing=True,
        misfire_grace_time=86400,
    )

    # 每年 1 月 1 日 03:00 生成上一年度的年度报告
    _scheduler.add_job(
        _gen_annual,
        trigger=CronTrigger(month=1, day=1, hour=3, minute=0),
        id='annual_report',
        name='BOL 年度报告自动生成',
        replace_existing=True,
        misfire_grace_time=86400,
    )

    _scheduler.start()
    logger.info('报告调度器已启动：季度报告（每季首日 02:00）· 年度报告（每年 1 月 1 日 03:00）')


def _gen_quarterly():
    try:
        from apps.reports.services import (
            generate_quarterly_report, latest_complete_quarter)
        year, quarter = latest_complete_quarter()
        generate_quarterly_report(year, quarter)
    except Exception as e:  # noqa: BLE001
        logger.error(f'季度报告自动生成失败: {e}', exc_info=True)


def _gen_annual():
    try:
        import datetime as dt
        from apps.reports.services import generate_annual_report
        generate_annual_report(dt.date.today().year - 1)
    except Exception as e:  # noqa: BLE001
        logger.error(f'年度报告自动生成失败: {e}', exc_info=True)


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info('报告调度器已关闭')
