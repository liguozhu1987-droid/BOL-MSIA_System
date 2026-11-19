from django.apps import AppConfig
from django.conf import settings


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    verbose_name = '人员管理'

    def ready(self):
        # 启动 SSO 员工状态回写调度器 (R8 核心: 中央表停用 -> 本地 INACTIVE + 清令牌)
        # - 非测试环境下启动
        # - DEBUG 模式 (开发环境) 默认不启动, 避免误操作数据库
        # - 通过环境变量 BOL_ENABLE_SCHEDULER=1 可强制在 DEBUG 模式下启动
        import os
        if not settings.DEBUG or os.environ.get('BOL_ENABLE_SCHEDULER'):
            from apps.users import scheduler
            scheduler.start_scheduler()
