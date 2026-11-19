# -*- coding: utf-8 -*-
"""分析模块 路由"""
from django.urls import path

from apps.analytics.views import (
    AchievableYoyView,
    BolComparisonView,
    BolLifecycleAllView,
    BudgetBolComparisonView,
    DashboardView,
    ImproveTargetCompareView,
    MultiDimBolAnalysisView,
    MultiDimBolTrendView,
)

urlpatterns = [
    # 1. 综合多维度 BOL 分析（工艺×RoofType×工厂×财年）
    path('comparison/', BolComparisonView.as_view(), name='analytics-comparison'),
    # 2. 综合看板概览
    path('dashboard/', DashboardView.as_view(), name='analytics-dashboard'),
    # 2.5 Achievable BOL 多年份同比（哑铃图，筛选器联动）
    path('achievable-yoy/', AchievableYoyView.as_view(), name='analytics-achievable-yoy'),
    # 2.6 改善目标对比（Budget/改善目标/Achievable 三工时哑铃图 + 下钻明细）
    path('improve-target-compare/', ImproveTargetCompareView.as_view(), name='analytics-improve-target-compare'),
    # 3. Budget BOL 财年对比分析
    path('budget-bol-comparison/', BudgetBolComparisonView.as_view(), name='analytics-budget-bol-comparison'),
    # 4. BOL 全链路对比全量数据（图表点击弹窗用）
    path('bol-lifecycle-all/', BolLifecycleAllView.as_view(), name='analytics-bol-lifecycle-all'),
    # 5. 综合多维度 BOL 分析（工艺×RoofType×工厂×财年）
    path('multi-dim-analysis/', MultiDimBolAnalysisView.as_view(), name='analytics-multi-dim-analysis'),
    # 6. 时间维度多 BOL 类型对比趋势
    path('multi-dim-trend/', MultiDimBolTrendView.as_view(), name='analytics-multi-dim-trend'),
]
