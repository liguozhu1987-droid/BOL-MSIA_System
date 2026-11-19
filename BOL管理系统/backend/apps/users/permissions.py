# -*- coding: utf-8 -*-
"""基于 Employee 角色的权限类"""
from rest_framework.permissions import BasePermission


class IsAuthenticatedEmployee(BasePermission):
    """要求已登录（request.user 为 Employee 实例）

    使用 is_authenticated 属性区分 Employee 与 AnonymousUser：
    - Employee.is_authenticated = True
    - AnonymousUser.is_authenticated = False
    """

    def has_permission(self, request, view):
        employee = getattr(request, 'user', None)
        if employee is None:
            return False
        if not getattr(employee, 'is_authenticated', False):
            return False
        if not getattr(employee, 'must_change_password', False):
            return True

        route_name = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
        if route_name in {'auth-change-password', 'auth-logout'}:
            return True
        return route_name == 'auth-me' and request.method == 'GET'


class HasRole(BasePermission):
    """要求用户角色在 allowed_roles 列表中"""

    allowed_roles = []

    def has_permission(self, request, view):
        employee = getattr(request, 'user', None)
        if not employee or not hasattr(employee, 'role'):
            return False
        if getattr(employee, 'must_change_password', False):
            return False
        return employee.role in self.allowed_roles


class IsAdmin(HasRole):
    allowed_roles = ['ADMIN']


class IsAdminOrIE(HasRole):
    allowed_roles = ['ADMIN', 'IE']


class CanManageEmployees(HasRole):
    """人员管理：仅管理员"""
    allowed_roles = ['ADMIN']
