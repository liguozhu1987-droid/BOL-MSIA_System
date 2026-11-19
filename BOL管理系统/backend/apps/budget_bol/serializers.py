# -*- coding: utf-8 -*-
"""年度预算BOL 序列化器"""
from rest_framework import serializers

from apps.budget_bol.models import BudgetBol, AchievableTargetBol


class BudgetBolSerializer(serializers.ModelSerializer):
    """Budget BOL 序列化器（对应 Excel 7列结构）"""

    class Meta:
        model = BudgetBol
        fields = '__all__'


class AchievableTargetBolSerializer(serializers.ModelSerializer):
    """Achievable/Target BOL 序列化器（对应 Excel 23列结构）"""

    class Meta:
        model = AchievableTargetBol
        fields = '__all__'
