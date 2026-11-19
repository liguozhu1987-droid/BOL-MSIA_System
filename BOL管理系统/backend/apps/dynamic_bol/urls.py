# -*- coding: utf-8 -*-
"""动态BOL 路由"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.dynamic_bol.views import (
    BolOverViewViewSet, BolOverViewByProcessViewSet,
    BolApprovalHistoryViewSet, BolUpdateHistoryViewSet,
    ApprovalOverviewStatsView, ApprovalTrendFilterOptionsView, ApprovalTrendView,
    LowLbAnalysisView, TopCompareView,
)

router = DefaultRouter()
router.register('overview', BolOverViewViewSet, basename='bol-overview')
router.register('by-process', BolOverViewByProcessViewSet, basename='bol-by-process')
router.register('approval-history', BolApprovalHistoryViewSet, basename='bol-approval-history')
router.register('update-history', BolUpdateHistoryViewSet, basename='bol-update-history')

urlpatterns = router.urls + [
    path('approval-overview-stats/', ApprovalOverviewStatsView.as_view(), name='bol-approval-overview-stats'),
    path('approval-trend-filter-options/', ApprovalTrendFilterOptionsView.as_view(), name='approval-trend-filter-options'),
    path('approval-trend/', ApprovalTrendView.as_view(), name='approval-trend'),
    path('low-lb-analysis/', LowLbAnalysisView.as_view(), name='low-lb-analysis'),
    path('top-compare/', TopCompareView.as_view(), name='top-compare'),
]
