# -*- coding: utf-8 -*-
"""人员管理 路由"""
from rest_framework.routers import DefaultRouter

from apps.users.views import EmployeeViewSet

router = DefaultRouter()
router.register('employees', EmployeeViewSet, basename='employee')

urlpatterns = router.urls
