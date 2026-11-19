# -*- coding: utf-8 -*-
"""项目主数据 路由"""
from rest_framework.routers import DefaultRouter

from apps.projects.views import ProgramInfoViewSet, BolUserViewSet, StationInfoViewSet

router = DefaultRouter()
router.register('programs', ProgramInfoViewSet, basename='program')
router.register('users', BolUserViewSet, basename='bol-user')
router.register('stations', StationInfoViewSet, basename='station')

urlpatterns = router.urls
