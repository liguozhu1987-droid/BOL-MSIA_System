# -*- coding: utf-8 -*-
"""人员管理 视图集"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response

from apps.users.authentication import EmployeeTokenAuthentication
from apps.users.models import Employee
from apps.users.permissions import CanManageEmployees, IsAuthenticatedEmployee
from apps.users.serializers import EmployeeSerializer


class EmployeeViewSet(viewsets.ModelViewSet):
    """员工 视图集：支持筛选、搜索、排序"""
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    authentication_classes = [EmployeeTokenAuthentication]
    permission_classes = [IsAuthenticatedEmployee, CanManageEmployees]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['department', 'role', 'status']
    search_fields = ['name', 'username', 'email', 'phone', 'title']
    ordering_fields = ['username', 'name', 'department', 'created_at']
    ordering = ['username']

    @action(detail=False, methods=['get'], url_path='active', permission_classes=[IsAuthenticatedEmployee])
    def active(self, request):
        """获取所有在职员工下拉列表（用于跟踪任务分派）"""
        qs = self.get_queryset().filter(status='ACTIVE').order_by('username')
        data = [
            {
                'id': e.id,
                'username': e.username,
                'name': e.name,
                'display_name': e.display_name,
                'department': e.department,
                'title': e.title,
                'role': e.role,
            }
            for e in qs
        ]
        return Response(data)

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """启用员工"""
        emp = self.get_object()
        emp.status = 'ACTIVE'
        emp.save(update_fields=['status', 'updated_at'])
        return Response({'status': 'ACTIVE'})

    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        """停用员工"""
        emp = self.get_object()
        emp.status = 'INACTIVE'
        emp.save(update_fields=['status', 'updated_at'])
        return Response({'status': 'INACTIVE'})
