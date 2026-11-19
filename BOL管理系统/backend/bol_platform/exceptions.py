# -*- coding: utf-8 -*-
"""REST Framework 全局异常处理"""
from rest_framework import status
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """未登录或令牌失效时返回 401，便于前端统一跳转登录页

    AnonymousUser.is_authenticated 为 False，Employee.is_authenticated 为 True，
    以此区分真实登录用户与匿名用户。
    """
    response = exception_handler(exc, context)
    if response is None:
        return response

    request = context.get('request')
    user = getattr(request, 'user', None) if request else None
    # 使用 is_authenticated 区分 Employee 与 AnonymousUser
    # （AnonymousUser 有 username 属性，但不能用 hasattr(user, 'username') 判断）
    is_authenticated = user is not None and getattr(user, 'is_authenticated', False)

    if response.status_code == status.HTTP_403_FORBIDDEN and not is_authenticated:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        if isinstance(response.data, dict):
            response.data['detail'] = '请先登录'

    return response
