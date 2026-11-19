# -*- coding: utf-8 -*-
from django.urls import path

from apps.reports.views import (
    ReportDeleteView,
    ReportDetailView,
    ReportEmailView,
    ReportGenerateView,
    ReportListView,
)

urlpatterns = [
    # 报告列表（所有登录用户可查阅，支持 report_type/year/search 筛选）
    path('reports/', ReportListView.as_view(), name='reports-list'),
    # 报告详情（完整 HTML）
    path('reports/<int:pk>/', ReportDetailView.as_view(), name='reports-detail'),
    # 手动生成（仅管理员）
    path('reports/generate/', ReportGenerateView.as_view(), name='reports-generate'),
    # 删除（仅管理员）
    path('reports/<int:pk>/delete/', ReportDeleteView.as_view(), name='reports-delete'),
    # 邮件推送报告（仅管理员，HTML 以附件发送）
    path('reports/<int:pk>/email/', ReportEmailView.as_view(), name='reports-email'),
]
