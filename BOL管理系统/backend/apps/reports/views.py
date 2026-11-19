# -*- coding: utf-8 -*-
"""报告生成模块 视图

权限口径：
  - 查阅（列表/详情）：所有已登录用户（报告供全公司查阅）
  - 生成/删除：仅管理员
  - 邮件推送：仅管理员
"""
import logging
import re

from django.db.models.functions import Length
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reports.models import GeneratedReport
from apps.reports.services import (
    generate_annual_report,
    generate_quarterly_report,
)
from apps.users.permissions import IsAdmin

logger = logging.getLogger(__name__)


def _int_param(data, name, default=None):
    v = data.get(name)
    if v in (None, ''):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class ReportListView(APIView):
    """报告列表（全部已登录用户可查阅，支持类型/年份/标题关键词筛选）"""

    def get(self, request):
        qs = GeneratedReport.objects.all().order_by('-year', '-quarter')
        report_type = request.query_params.get('report_type')
        if report_type:
            qs = qs.filter(report_type=report_type)
        year = request.query_params.get('year')
        if year:
            qs = qs.filter(year=year)
        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(title__icontains=search)
        count = qs.count()
        summaries = qs.defer('html').annotate(
            html_length=Length('html')
        )
        return Response({
            'count': count,
            'results': [
                report.to_summary(html_size_kb=report.html_length / 1024)
                for report in summaries
            ],
        })


class ReportDetailView(APIView):
    """报告详情（完整 HTML 内容）"""

    def get(self, request, pk):
        try:
            r = GeneratedReport.objects.get(pk=pk)
        except GeneratedReport.DoesNotExist:
            return Response({'detail': '报告不存在'}, status=status.HTTP_404_NOT_FOUND)
        data = r.to_summary()
        data['html'] = r.html
        return Response(data)


class ReportGenerateView(APIView):
    """手动生成报告（仅管理员）"""

    permission_classes = [IsAdmin]

    def post(self, request):
        report_type = (request.data.get('report_type') or '').strip()
        year = _int_param(request.data, 'year')
        quarter = _int_param(request.data, 'quarter')
        import datetime as dt
        today = dt.date.today()

        operator = f'{request.user.username} {request.user.name}'.strip()

        try:
            if report_type == 'QUARTERLY':
                if year is None or quarter is None:
                    return Response(
                        {'detail': '季度报告需指定年份和季度'},
                        status=status.HTTP_400_BAD_REQUEST)
                if not (1 <= quarter <= 4):
                    return Response(
                        {'detail': '季度取值应为 1-4'},
                        status=status.HTTP_400_BAD_REQUEST)
                obj, _ = generate_quarterly_report(
                    year, quarter, generated_by=operator, today=today)
            elif report_type == 'ANNUAL':
                if year is None:
                    return Response(
                        {'detail': '年度报告需指定年份'},
                        status=status.HTTP_400_BAD_REQUEST)
                obj, _ = generate_annual_report(
                    year, generated_by=operator, today=today)
            else:
                return Response(
                    {'detail': 'report_type 应为 QUARTERLY 或 ANNUAL'},
                    status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # noqa: BLE001
            logger.error(f'报告生成失败: {e}', exc_info=True)
            return Response(
                {'detail': f'报告生成失败: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'detail': f'报告已生成: {obj.title}',
            'report': obj.to_summary(),
        }, status=status.HTTP_201_CREATED)


class ReportDeleteView(APIView):
    """删除报告（仅管理员）"""

    permission_classes = [IsAdmin]

    def delete(self, request, pk):
        try:
            r = GeneratedReport.objects.get(pk=pk)
        except GeneratedReport.DoesNotExist:
            return Response({'detail': '报告不存在'}, status=status.HTTP_404_NOT_FOUND)
        title = r.title
        r.delete()
        return Response({'detail': f'已删除: {title}'})


class ReportEmailView(APIView):
    """邮件推送报告（仅管理员）

    报告为完整 HTML 快照（含内联 ECharts），体积较大，以 HTML 附件形式发送；
    正文使用纯文本，确保 Outlook 等客户端兼容。
    """

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            r = GeneratedReport.objects.get(pk=pk)
        except GeneratedReport.DoesNotExist:
            return Response({'detail': '报告不存在'}, status=status.HTTP_404_NOT_FOUND)

        raw = request.data.get('recipients')
        if isinstance(raw, str):
            raw = re.split(r'[,;\s]+', raw)
        recipients = [x.strip() for x in (raw or []) if x.strip()]
        if not recipients:
            return Response(
                {'detail': '请至少填写一个收件人邮箱'},
                status=status.HTTP_400_BAD_REQUEST)

        invalid = [x for x in recipients if not re.match(
            r'^[^@\s]+@[^@\s]+\.[^@\s]+$', x)]
        if invalid:
            return Response(
                {'detail': f'收件人邮箱格式不正确: {", ".join(invalid)}'},
                status=status.HTTP_400_BAD_REQUEST)

        note = (request.data.get('message') or '').strip()

        from django.core.mail import EmailMessage
        body_lines = [
            f'您好，',
            '',
            f'BOL 管理分析平台报告已推送，请查收附件（浏览器打开即可查阅图表）。',
            '',
            f'报告标题: {r.title}',
            f'数据区间: {r.period_start} ~ {r.period_end}',
            f'生成时间: {r.created_at.strftime("%Y-%m-%d %H:%M")}',
        ]
        if note:
            body_lines += ['', f'附言: {note}']
        body_lines += ['', '— BOL 管理分析平台（系统自动发送，请勿回复）']

        safe_name = re.sub(r'[\\/:*?"<>|]', '_', r.title)
        msg = EmailMessage(
            subject=f'[BOL 平台] {r.title}',
            body='\n'.join(body_lines),
            to=recipients,
        )
        msg.attach(f'{safe_name}.html', r.html, 'text/html; charset=utf-8')

        try:
            msg.send()
        except Exception as e:  # noqa: BLE001
            logger.error(f'报告邮件发送失败: {e}', exc_info=True)
            return Response(
                {'detail': f'邮件发送失败: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'detail': f'已发送至 {len(recipients)} 个收件人',
            'recipients': recipients,
        })
