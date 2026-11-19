# -*- coding: utf-8 -*-
"""从 SSO 中央表回写 BOL 员工状态 (R8 核心, 方案文档 6.2)

每小时执行 (users 应用调度器):
  中央表 CN_AME.dbo.CN_AME_SSO_User.status=0 -> 本地 Employee.status='INACTIVE'
     并清除该员工的 AuthToken (双轨期旧本地 Token 最长 7/30 天有效,
     仅靠 Keycloak 禁用挡不住旧 Token —— 本命令把离职缺口压到 <=1 小时)
  中央表 status=1 且本地 INACTIVE -> 恢复 ACTIVE

覆盖范围: 中央表**全量用户** (LEFT JOIN UserMap, 无映射者回落 login_name)。
QA Round 1 修复 (T05-R1 #1): 原实现只 JOIN UserMap 取人, UserMap 仅 2 条 bol
映射, admin/ligu/chenca/libi2 等无映射员工的 status=0 不传导, 旧 local Token
离职后仍有效 7/30 天 —— R8/S4 缺口。改为全量中央表后该缺口关闭。
游客 (guest) 不在中央表, 天然不受影响。

跨库: BOL 连接在 CMC 库, 与 CN_AME 同实例, 三段名直接跨库只读
(sparePartRead 已授权 SELECT CN_AME_SSO_User/UserMap, T01 02_grants.sql)。

用法:
    python manage.py sync_sso_status [--dry-run]
"""
import logging

from django.core.management.base import BaseCommand
from django.db import connections

from apps.users.models import AuthToken, Employee

logger = logging.getLogger(__name__)

# 中央表 -> 本地状态回写查询 (全量中央用户; 有映射用 local_username, 无映射回落 login_name)
_SYNC_SQL = (
    "SELECT COALESCE(m.local_username, u.login_name) AS local_username, u.status "
    "FROM CN_AME.dbo.CN_AME_SSO_User u "
    "LEFT JOIN CN_AME.dbo.CN_AME_SSO_UserMap m "
    "ON m.employee_no = u.employee_no AND m.system_code = %s"
)

# 中央表 status 语义 (与 MSIA 一致): 1=在职, 0=停用
_CENTRAL_ACTIVE = 1


class Command(BaseCommand):
    help = '从 CN_AME SSO 中央表回写员工状态 (停用传导 + 清除本地令牌)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run', default=False,
            help='试运行: 只输出将要执行的变更, 不写数据库 (切换日演练用)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write('[DRY-RUN] 试运行模式, 不会写入任何变更')

        # 1. 读取中央表 (跨库, 只读)
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute(_SYNC_SQL, ['bol'])
                rows = cursor.fetchall()
        except Exception as e:
            logger.exception('sync_sso_status: 读取中央对照表失败')
            self.stderr.write(f'[失败] 读取中央对照表失败: {e}')
            return

        if not rows:
            self.stdout.write('中央表无用户记录, 无需回写')
            return

        # 2. 逐条回写 (local_username -> Employee.username)
        stats = {'checked': 0, 'disabled': 0, 'reactivated': 0, 'skipped': 0, 'tokens_cleared': 0}
        for local_username, central_status in rows:
            stats['checked'] += 1
            local_username = str(local_username).strip()
            employee = Employee.objects.filter(username=local_username).first()

            if employee is None:
                # 中央表有记录但本地无账号 (未首次登录): 跳过, 不猜测不建档
                stats['skipped'] += 1
                logger.info(
                    'sync_sso_status: 中央表用户 %s 本地无账号, 跳过 (等待首次 OIDC 登录自动建档)',
                    local_username,
                )
                continue

            if int(central_status) == _CENTRAL_ACTIVE:
                # 在职: 本地被停用则恢复 (如复职)
                if employee.status != 'ACTIVE':
                    if not dry_run:
                        employee.status = 'ACTIVE'
                        employee.save(update_fields=['status', 'updated_at'])
                    stats['reactivated'] += 1
                    logger.info('sync_sso_status: %s 恢复 ACTIVE (中央表在职)', local_username)
                continue

            # 停用: 本地未停用则停用 (游客不在中央表, 天然不受影响)
            if employee.status != 'INACTIVE':
                if not dry_run:
                    employee.status = 'INACTIVE'
                    employee.save(update_fields=['status', 'updated_at'])
                stats['disabled'] += 1
                logger.warning(
                    'sync_sso_status: %s 停用传导 (中央表离职/停用)', local_username,
                )

            # R8 安全纵深 (QA Round 2 minor 修复): 中央表停用即无条件清令牌,
            # 清理动作不包在 "状态转换" 分支内 —— 避免本地已 INACTIVE 但历史 Token
            # 残留时不清除, 复职后旧 Token 重新可用的复活窗口。
            if not dry_run:
                deleted, _ = AuthToken.objects.filter(employee=employee).delete()
                stats['tokens_cleared'] += deleted
                if deleted:
                    logger.warning(
                        'sync_sso_status: %s 中央表停用, 已清理残留本地令牌 %d 条',
                        local_username, deleted,
                    )

        # 3. 汇总日志 (调度器每小时调用, 便于健康检查)
        summary = (
            f"sync_sso_status 完成: 核对 {stats['checked']} 人, "
            f"新停用 {stats['disabled']} 人 (清令牌 {stats['tokens_cleared']} 条), "
            f"恢复 {stats['reactivated']} 人, 跳过(本地无账号) {stats['skipped']} 人"
        )
        if dry_run:
            summary = '[DRY-RUN] ' + summary
        logger.info(summary)
        self.stdout.write(summary)
