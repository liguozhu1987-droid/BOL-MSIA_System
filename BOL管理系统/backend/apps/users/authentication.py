# -*- coding: utf-8 -*-
"""Token 认证：基于 AuthToken 模型"""
from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.users.models import AuthToken


class EmployeeTokenAuthentication(authentication.BaseAuthentication):
    """从 Authorization: Token <key> 头解析并验证登录令牌"""

    keyword = 'Token'

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request)
        if not auth_header:
            return None

        parts = auth_header.decode('utf-8').split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        return self.authenticate_credentials(parts[1])

    def authenticate_credentials(self, key):
        try:
            token = AuthToken.objects.select_related('employee').get(key=key)
        except AuthToken.DoesNotExist:
            raise exceptions.AuthenticationFailed('无效或已过期的登录令牌')

        if token.is_expired:
            token.delete()
            raise exceptions.AuthenticationFailed('登录已过期，请重新登录')

        employee = token.employee
        if employee.status != 'ACTIVE':
            raise exceptions.AuthenticationFailed('账号已停用，请联系管理员')

        return (employee, token)
