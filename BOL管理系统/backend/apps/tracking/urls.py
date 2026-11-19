# -*- coding: utf-8 -*-
"""高BOL跟踪 路由"""
from rest_framework.routers import DefaultRouter

from apps.tracking.views import HighBolTrackingViewSet, ImprovementLogViewSet

router = DefaultRouter()
router.register('high-bol-tracking', HighBolTrackingViewSet, basename='high-bol-tracking')
router.register('improvement-log', ImprovementLogViewSet, basename='improvement-log')

urlpatterns = router.urls
