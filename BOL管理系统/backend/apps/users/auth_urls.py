# -*- coding: utf-8 -*-
"""认证路由"""
from django.urls import path

from apps.users.auth_views import (
    ChangePasswordView,
    ForgotPasswordView,
    GuestLoginView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
)
from apps.users.oidc_views import (
    AuthConfigView,
    OidcTokenView,
    oidc_callback,
    oidc_login,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('guest-login/', GuestLoginView.as_view(), name='auth-guest-login'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', MeView.as_view(), name='auth-me'),
    path('change-password/', ChangePasswordView.as_view(), name='auth-change-password'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='auth-forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='auth-reset-password'),
    # 登录页功能开关 (公开, OIDC/本地登录/自助注册/密码自助)
    path('config/', AuthConfigView.as_view(), name='auth-config'),
    # 统一身份登录 (Keycloak OIDC 授权码流, 方案文档第 6 章)
    path('oidc/login/', oidc_login, name='auth-oidc-login'),
    path('oidc/callback/', oidc_callback, name='auth-oidc-callback'),
    path('oidc/token/', OidcTokenView.as_view(), name='auth-oidc-token'),
]
