# -*- coding: utf-8 -*-
"""报告生成模块应用配置"""
from django.apps import AppConfig
from django.conf import settings


class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reports'
    verbose_name = '报告生成'

    def ready(self):
        # 与 analytics 调度器相同的启动策略：
        # - 非测试环境下启动
        # - DEBUG 模式（开发环境）默认不启动，避免开发期间误生成报告
        # - 通过环境变量 BOL_ENABLE_SCHEDULER=1 可强制启动
        import os
        if not settings.DEBUG or os.environ.get('BOL_ENABLE_SCHEDULER'):
            from apps.reports import scheduler
            scheduler.start_scheduler()
