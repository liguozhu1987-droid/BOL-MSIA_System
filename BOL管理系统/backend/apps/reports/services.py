# -*- coding: utf-8 -*-
"""报告生成编排：提取数据 → 渲染 HTML → 存库

同一周期的报告重新生成时全量替换（同 Budget BOL 导入口径）。
"""
import datetime as dt
import logging

from apps.reports.models import GeneratedReport
from apps.reports.report_data import extract_quarter_data, extract_year_data
from apps.reports.report_html import build_quarter, build_year

logger = logging.getLogger(__name__)


def generate_quarterly_report(year, quarter, generated_by='系统自动', today=None):
    """生成季度报告并入库（同周期全量替换）

    返回 (GeneratedReport, created)
    """
    if not (1 <= quarter <= 4):
        raise ValueError(f'非法季度: {quarter}')
    today = today or dt.date.today()

    Q = extract_quarter_data(year, quarter, today=today)
    html_text = build_quarter(Q)

    title = f'BOL 季度分析报告 · {year} Q{quarter}'
    obj, created = GeneratedReport.objects.update_or_create(
        report_type='QUARTERLY', year=year, quarter=quarter,
        defaults={
            'title': title,
            'period_start': dt.date.fromisoformat(Q['qs']),
            'period_end': dt.date.fromisoformat(Q['qe']),
            'html': html_text,
            'generated_by': generated_by,
        },
    )
    logger.info(f'季度报告已生成: {title}（{generated_by}，HTML {len(html_text) // 1024} KB）')
    return obj, created


def generate_annual_report(year, generated_by='系统自动', today=None):
    """生成年度报告并入库（同周期全量替换）

    返回 (GeneratedReport, created)
    """
    today = today or dt.date.today()

    Y = extract_year_data(year, today=today)
    html_text = build_year(Y)

    title = f'BOL 年度分析报告 · {year}'
    obj, created = GeneratedReport.objects.update_or_create(
        report_type='ANNUAL', year=year, quarter=None,
        defaults={
            'title': title,
            'period_start': dt.date(year, 1, 1),
            'period_end': dt.date.fromisoformat(Y['data_end']),
            'html': html_text,
            'generated_by': generated_by,
        },
    )
    logger.info(f'年度报告已生成: {title}（{generated_by}，HTML {len(html_text) // 1024} KB）')
    return obj, created


def latest_complete_quarter(today=None):
    """最近一个完整自然季度（生成日期所处季度的上一季）

    返回 (year, quarter)
    """
    today = today or dt.date.today()
    q = (today.month - 1) // 3 + 1
    if q == 1:
        return today.year - 1, 4
    return today.year, q - 1
