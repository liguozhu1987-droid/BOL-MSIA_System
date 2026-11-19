# -*- coding: utf-8 -*-
"""实测CT 序列化器"""
from rest_framework import serializers
from apps.actual_ct.models import RealCtExtract, RealCtExtractPerDay, BottleNeckCt, CtRealtimeStatus


class RealCtExtractSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealCtExtract
        fields = '__all__'


class RealCtExtractPerDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = RealCtExtractPerDay
        fields = '__all__'


class BottleNeckCtSerializer(serializers.ModelSerializer):
    class Meta:
        model = BottleNeckCt
        fields = '__all__'


class CtRealtimeStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = CtRealtimeStatus
        fields = '__all__'
