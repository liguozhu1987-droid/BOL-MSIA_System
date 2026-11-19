# -*- coding: utf-8 -*-
"""实测CT 路由"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.actual_ct.views import (
    RealCtExtractViewSet, RealCtExtractPerDayViewSet,
    BottleNeckCtViewSet, CtRealtimeStatusViewSet, CtAnalysisViewSet,
    CascadeFilterView, SctVsActView, LineBalanceView, BoxPlotView,
    ActualCtSearchView, StationCtDetailView,
    CtTrendTopView, ActStdDeviationView,
)

router = DefaultRouter()
router.register('real-ct', RealCtExtractViewSet, basename='real-ct')
router.register('real-ct-per-day', RealCtExtractPerDayViewSet, basename='real-ct-per-day')
router.register('bottleneck-ct', BottleNeckCtViewSet, basename='bottleneck-ct')
router.register('realtime-status', CtRealtimeStatusViewSet, basename='realtime-status')
router.register('analysis', CtAnalysisViewSet, basename='analysis')

urlpatterns = router.urls + [
    path('cascade-filters/', CascadeFilterView.as_view(), name='cascade-filters'),
    path('sct-vs-act/', SctVsActView.as_view(), name='sct-vs-act'),
    path('line-balance/', LineBalanceView.as_view(), name='line-balance'),
    path('box-plot/', BoxPlotView.as_view(), name='box-plot'),
    path('search/', ActualCtSearchView.as_view(), name='actual-ct-search'),
    path('station-detail/', StationCtDetailView.as_view(), name='station-detail'),
    path('ct-trend-top/', CtTrendTopView.as_view(), name='ct-trend-top'),
    path('act-std-deviation/', ActStdDeviationView.as_view(), name='act-std-deviation'),
]
