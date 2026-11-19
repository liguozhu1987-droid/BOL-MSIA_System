# -*- coding: utf-8 -*-
"""报告生成模型 - CMC库可读写

存储系统自动/手动生成的季度与年度分析报告（standalone HTML 快照）。
报告 HTML 为生成时点的完整快照（内联 CSS + ECharts），供用户随时查阅，
不随源数据变化而变化。
"""
from django.conf import settings
from django.db import models


class GeneratedReport(models.Model):
    """已生成的分析报告（季度/年度）"""

    REPORT_TYPES = [
        ('QUARTERLY', '季度报告'),
        ('ANNUAL', '年度报告'),
    ]

    report_type = models.CharField(
        max_length=20, choices=REPORT_TYPES, verbose_name='报告类型')
    year = models.IntegerField(verbose_name='年份')
    quarter = models.IntegerField(
        null=True, blank=True, verbose_name='季度',
        help_text='仅季度报告有值（1-4），年度报告为空')
    title = models.CharField(max_length=200, verbose_name='报告标题')
    period_start = models.DateField(verbose_name='数据起始日期')
    period_end = models.DateField(verbose_name='数据截止日期')
    html = models.TextField(verbose_name='报告HTML内容（完整快照）')
    generated_by = models.CharField(
        max_length=100, blank=True, verbose_name='生成人',
        help_text='手动生成时记录操作人，自动生成时为"系统自动"')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次生成时间')
    # 同周期重新生成时全量替换（update_or_create），created_at（auto_now_add）不会刷新，
    # updated_at 记录最近一次生成时间，供列表展示，避免用户误以为生成未生效
    updated_at = models.DateTimeField(auto_now=True, verbose_name='最近生成时间')

    class Meta:
        managed = True
        db_table = 'CN_IE_BOL_GeneratedReport'
        app_label = 'reports'
        verbose_name = '分析报告'
        verbose_name_plural = verbose_name
        ordering = ['-year', '-quarter', '-created_at']
        indexes = [
            models.Index(fields=['report_type', 'year']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['report_type', 'year', 'quarter'],
                name='uq_report_period',
            ),
        ]

    def __str__(self):
        period = f'{self.year}Q{self.quarter}' if self.quarter else str(self.year)
        return f'{self.get_report_type_display()} · {period}'

    @property
    def period_label(self):
        """报告周期展示标签：2026Q2 / 2026"""
        return f'{self.year}Q{self.quarter}' if self.quarter else str(self.year)

    @property
    def is_manual(self):
        return self.generated_by != '系统自动'

    def to_summary(self, html_size_kb=None):
        """列表用摘要（不含 HTML 大字段）"""
        return {
            'id': self.id,
            'report_type': self.report_type,
            'report_type_label': self.get_report_type_display(),
            'year': self.year,
            'quarter': self.quarter,
            'period_label': self.period_label,
            'title': self.title,
            'period_start': str(self.period_start),
            'period_end': str(self.period_end),
            'generated_by': self.generated_by,
            'created_at': timezone_bj(self.created_at),
            'updated_at': timezone_bj(self.updated_at) or timezone_bj(self.created_at),
            'html_size_kb': round(
                html_size_kb if html_size_kb is not None else len(self.html) / 1024,
                1,
            ),
        }


def timezone_bj(dt):
    """统一转换为北京时间字符串（东八区）"""
    from django.utils import timezone as dj_tz
    if dt is None:
        return None
    if dj_tz.is_naive(dt):
        dt = dt.replace(tzinfo=dj_tz.utc)
    return dj_tz.localtime(dt, dj_tz.get_fixed_timezone(480)).strftime(
        '%Y-%m-%d %H:%M:%S')
