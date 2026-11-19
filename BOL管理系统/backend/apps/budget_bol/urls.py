# -*- coding: utf-8 -*-
"""年度预算BOL 路由"""
from rest_framework.routers import DefaultRouter

from apps.budget_bol.views import BudgetBolViewSet

router = DefaultRouter()
router.register('budget-bol', BudgetBolViewSet, basename='budget-bol')

urlpatterns = router.urls
