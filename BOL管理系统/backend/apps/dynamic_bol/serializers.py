# -*- coding: utf-8 -*-
"""动态BOL 序列化器"""
from rest_framework import serializers
from apps.dynamic_bol.models import BolOverView, BolOverViewByProcess, BolApprovalHistory, BolUpdateHistory


class BolOverViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = BolOverView
        fields = '__all__'


class BolOverViewByProcessSerializer(serializers.ModelSerializer):
    class Meta:
        model = BolOverViewByProcess
        fields = '__all__'


class BolApprovalHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BolApprovalHistory
        fields = '__all__'


class BolUpdateHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BolUpdateHistory
        fields = '__all__'
