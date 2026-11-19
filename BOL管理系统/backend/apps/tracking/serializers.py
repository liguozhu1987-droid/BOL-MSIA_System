# -*- coding: utf-8 -*-
"""高BOL跟踪 序列化器"""
from rest_framework import serializers

from apps.tracking.models import HighBolTracking, ImprovementLog


class ImprovementLogSerializer(serializers.ModelSerializer):
    """改善日志序列化器"""

    class Meta:
        model = ImprovementLog
        fields = '__all__'


class HighBolTrackingSerializer(serializers.ModelSerializer):
    """高BOL跟踪序列化器

    状态流转与审计字段均设为只读，必须通过 start/achieve/verify/close/reopen
    等 action 完成状态机流转，防止 PUT/POST 直接绕过状态校验与审计日志。
    bol_gap、cost_gap 由模型 save 自动计算。
    """
    logs = ImprovementLogSerializer(many=True, read_only=True)

    class Meta:
        model = HighBolTracking
        fields = '__all__'
        read_only_fields = [
            # 自动计算字段
            'bol_gap', 'cost_gap',
            # 状态流转字段（仅可通过 action 修改）
            'status',
            # 流转时间节点
            'assigned_at', 'started_at', 'achieved_at',
            'verified_at', 'closed_at', 'updated_at',
            # 验证/关闭审计字段
            'verified_by', 'verified_by_name', 'verify_comment',
            'closed_by', 'closed_by_name',
            # 创建审计
            'created_at',
        ]
