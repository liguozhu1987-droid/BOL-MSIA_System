# -*- coding: utf-8 -*-
"""分析模块应用配置"""
from django.apps import AppConfig
from django.conf import settings


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.analytics'

    def ready(self):
        # 启动定时任务调度器
        # - 非测试环境下启动
        # - DEBUG 模式（开发环境）默认不启动，避免误发邮件
        # - 通过环境变量 BOL_ENABLE_SCHEDULER=1 可强制在 DEBUG 模式下启动
        import os
        if not settings.DEBUG or os.environ.get('BOL_ENABLE_SCHEDULER'):
            from apps.analytics import scheduler
            scheduler.start_scheduler()
