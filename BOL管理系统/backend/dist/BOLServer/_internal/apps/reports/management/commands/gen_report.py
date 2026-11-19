# -*- coding: utf-8 -*-
"""手动/命令行生成报告

用法：
  python manage.py gen_report --type quarterly --year 2026 --quarter 2
  python manage.py gen_report --type annual --year 2026
  python manage.py gen_report --type quarterly   # 缺省生成最近完整季度
  python manage.py gen_report --type annual      # 缺省生成当前年份
"""
from django.core.management.base import BaseCommand, CommandError

from apps.reports.services import (
    generate_annual_report,
    generate_quarterly_report,
    latest_complete_quarter,
)


class Command(BaseCommand):
    help = '生成 BOL 季度/年度分析报告（standalone HTML 快照）'

    def add_arguments(self, parser):
        parser.add_argument('--type', required=True,
                            choices=['quarterly', 'annual'], help='报告类型')
        parser.add_argument('--year', type=int, default=None, help='年份（缺省自动推断）')
        parser.add_argument('--quarter', type=int, default=None, help='季度 1-4（仅季度报告）')

    def handle(self, *args, **options):
        rtype = options['type']
        year = options['year']
        quarter = options['quarter']

        try:
            if rtype == 'quarterly':
                if year is None or quarter is None:
                    year, quarter = latest_complete_quarter()
                obj, created = generate_quarterly_report(year, quarter)
            else:
                import datetime as dt
                if year is None:
                    year = dt.date.today().year
                obj, created = generate_annual_report(year)
        except Exception as e:  # noqa: BLE001
            raise CommandError(f'报告生成失败: {e}') from e

        action = '新建' if created else '替换'
        self.stdout.write(self.style.SUCCESS(
            f'已{action}: {obj.title}（数据 {obj.period_start} ~ {obj.period_end}，'
            f'HTML {len(obj.html) // 1024} KB）'))
