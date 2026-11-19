# -*- coding: utf-8 -*-
"""项目主数据 视图"""
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from apps.projects.models import ProgramInfo, BolUser, StationInfo
from apps.projects.serializers import ProgramInfoSerializer, BolUserSerializer, StationInfoSerializer


class ProgramInfoViewSet(viewsets.ReadOnlyModelViewSet):
    """项目主数据（HRDB 只读）"""
    queryset = ProgramInfo.objects.all()
    serializer_class = ProgramInfoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['location', 'program_status', 'customer_name', 'product_type', 'process_type']
    search_fields = ['program_code', 'program_name', 'customer_name', 'related_program_code']
    ordering_fields = ['program_code', 'update_date', 'program_name']
    ordering = ['-update_date']


class BolUserViewSet(viewsets.ReadOnlyModelViewSet):
    """系统用户（HRDB 只读）"""
    queryset = BolUser.objects.all()
    serializer_class = BolUserSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['location', 'station']
    search_fields = ['real_name', 'user_name']
    ordering_fields = ['user_name', 'real_name']


class StationInfoViewSet(viewsets.ReadOnlyModelViewSet):
    """工位信息（HRDB 只读）"""
    queryset = StationInfo.objects.all()
    serializer_class = StationInfoSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['program_code', 'process', 'line_nr', 'station_type']
    search_fields = ['station_code', 'station_name', 'bol_nr']
    ordering_fields = ['program_code', 'process', 'station_code']
