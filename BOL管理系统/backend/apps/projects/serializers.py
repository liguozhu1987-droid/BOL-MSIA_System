# -*- coding: utf-8 -*-
"""项目主数据 序列化器"""
from rest_framework import serializers
from apps.projects.models import ProgramInfo, BolUser, StationInfo


class ProgramInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgramInfo
        fields = '__all__'


class BolUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = BolUser
        fields = '__all__'


class StationInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = StationInfo
        fields = '__all__'
