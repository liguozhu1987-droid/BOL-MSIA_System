# -*- coding: utf-8 -*-
"""认证 API 视图"""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.auth_serializers import (
    ChangePasswordSerializer,
    EmployeeProfileSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
)
from apps.users.authentication import EmployeeTokenAuthentication
from apps.users.models import AuthToken, Employee, PasswordResetToken
from apps.users.permissions import IsAuthenticatedEmployee


def _build_login_response(employee, token):
    return {
        'token': token.key,
        'expires_at': token.expires_at.isoformat(),
        'user': EmployeeProfileSerializer(employee).data,
    }


def _feature_disabled_response(detail):
    """功能开关关闭时的统一 403 响应 (方案文档 6.2 开关矩阵)"""
    return Response({'detail': detail}, status=status.HTTP_403_FORBIDDEN)


class RegisterView(APIView):
    """用户自助注册 (R7: SELF_REGISTRATION_ENABLED=False 时关闭, 代码保留配置禁用)"""
    permission_classes = [AllowAny]

    def post(self, request):
        # R7: 自助注册是影子账号最大来源, 统一身份认证期间关闭 (P4 起不再恢复)
        if not getattr(settings, 'SELF_REGISTRATION_ENABLED', False):
            return _feature_disabled_response('自助注册已关闭，请联系管理员开通账号')
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = serializer.save()
        expire_hours = getattr(settings, 'AUTH_TOKEN_EXPIRE_HOURS', 168)
        token = AuthToken.create_for_employee(employee, expire_hours=expire_hours)
        employee.last_login = timezone.now()
        employee.save(update_fields=['last_login'])
        return Response(_build_login_response(employee, token), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """用户登录（支持"保持登录"：remember=true 时发放 30 天令牌，否则 7 天）

    双轨开关: LOCAL_AUTH_ENABLED=False 时本地账密登录关闭 (P4 单轨切换),
    仅保留统一身份登录 (OIDC) 与游客通道。
    """
    permission_classes = [AllowAny]
    REMEMBER_EXPIRE_HOURS = 720  # 30 天

    def post(self, request):
        # 双轨开关: 本地登录关闭后统一走 Keycloak (方案文档 8.1 开关矩阵)
        if not getattr(settings, 'LOCAL_AUTH_ENABLED', True):
            return _feature_disabled_response('本地登录已关闭，请使用统一身份登录')
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = serializer.validated_data['employee']
        remember = request.data.get('remember', False)
        if remember and str(remember).lower() in ('true', '1', 'yes'):
            expire_hours = self.REMEMBER_EXPIRE_HOURS
        else:
            expire_hours = getattr(settings, 'AUTH_TOKEN_EXPIRE_HOURS', 168)
        token = AuthToken.create_for_employee(employee, expire_hours=expire_hours)
        employee.last_login = timezone.now()
        employee.save(update_fields=['last_login'])
        return Response(_build_login_response(employee, token))


class GuestLoginView(APIView):
    """游客登录：无需注册，使用固定游客账号生成临时令牌

    游客权限受限，仅能查看部分模块（前端路由 meta.guest_allowed 控制）。
    令牌有效期较短（默认 24 小时），每次调用生成新令牌。
    """
    permission_classes = [AllowAny]
    GUEST_USERNAME = 'guest'
    GUEST_EXPIRE_HOURS = 24

    def post(self, request):
        employee, _ = Employee.objects.get_or_create(
            username=self.GUEST_USERNAME,
            defaults={
                'name': '游客',
                'role': 'GUEST',
                'status': 'ACTIVE',
                'email': '',
                'department': '',
                'title': '访客',
            },
        )
        # 确保游客角色正确（防止旧数据 role 不是 GUEST）
        if employee.role != 'GUEST':
            employee.role = 'GUEST'
            employee.status = 'ACTIVE'
            employee.save(update_fields=['role', 'status', 'updated_at'])

        token = AuthToken.create_for_employee(
            employee, expire_hours=self.GUEST_EXPIRE_HOURS
        )
        employee.last_login = timezone.now()
        employee.save(update_fields=['last_login'])
        return Response(_build_login_response(employee, token))


class LogoutView(APIView):
    """退出登录（销毁当前令牌）"""
    authentication_classes = [EmployeeTokenAuthentication]
    permission_classes = [IsAuthenticatedEmployee]

    def post(self, request):
        auth = request.auth
        if auth:
            auth.delete()
        return Response({'detail': '已退出登录'})


class MeView(APIView):
    """获取当前登录用户信息"""
    authentication_classes = [EmployeeTokenAuthentication]
    permission_classes = [IsAuthenticatedEmployee]

    def get(self, request):
        return Response(EmployeeProfileSerializer(request.user).data)

    def patch(self, request):
        """更新个人资料（不含角色/状态）"""
        employee = request.user
        allowed = {'name', 'email', 'phone', 'department', 'title'}
        data = {k: v for k, v in request.data.items() if k in allowed}
        for field, value in data.items():
            setattr(employee, field, value)
        employee.save(update_fields=list(data.keys()) + ['updated_at'])
        return Response(EmployeeProfileSerializer(employee).data)


class ChangePasswordView(APIView):
    """修改密码（需验证原密码）

    双轨开关: PASSWORD_SELF_SERVICE_ENABLED=False 时密码自助服务下线 (R14),
    改密/找回密码均由 Keycloak 控制台接管。
    """
    authentication_classes = [EmployeeTokenAuthentication]
    permission_classes = [IsAuthenticatedEmployee]

    def post(self, request):
        if not getattr(settings, 'PASSWORD_SELF_SERVICE_ENABLED', True):
            return _feature_disabled_response('密码自助服务已关闭，请在统一身份平台自助修改密码')
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'employee': request.user},
        )
        serializer.is_valid(raise_exception=True)
        employee = request.user
        employee.set_password(serializer.validated_data['new_password'])
        employee.must_change_password = False
        employee.save(update_fields=['password', 'must_change_password', 'updated_at'])
        AuthToken.objects.filter(employee=employee).exclude(key=request.auth.key).delete()
        return Response({'detail': '密码修改成功'})


class ForgotPasswordView(APIView):
    """忘记密码：验证用户名+邮箱后生成重置令牌

    双轨开关: PASSWORD_SELF_SERVICE_ENABLED=False 时密码自助服务下线 (R14)。
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not getattr(settings, 'PASSWORD_SELF_SERVICE_ENABLED', True):
            return _feature_disabled_response('密码自助服务已关闭，请在统一身份平台自助重置密码')
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = serializer.validated_data['employee']
        expire_hours = getattr(settings, 'PASSWORD_RESET_EXPIRE_HOURS', 1)
        reset_token = PasswordResetToken.create_for_employee(employee, expire_hours=expire_hours)

        reset_path = f"/reset-password?token={reset_token.token}"
        message = '密码重置链接已生成，请在有效期内完成重置'

        if employee.email and hasattr(settings, 'EMAIL_HOST') and settings.EMAIL_HOST:
            try:
                send_mail(
                    subject='BOL 管理分析平台 - 密码重置',
                    message=(
                        f'您好 {employee.name}，\n\n'
                        f'请点击以下链接重置密码（{expire_hours} 小时内有效）：\n'
                        f'{getattr(settings, "FRONTEND_BASE_URL", "")}{reset_path}\n\n'
                        f'如非本人操作，请忽略此邮件。'
                    ),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bol.local'),
                    recipient_list=[employee.email],
                    fail_silently=False,
                )
                message = '重置链接已发送至您的邮箱，请查收'
            except Exception:
                message = '邮件发送失败，请联系管理员协助重置密码'

        response_data = {'detail': message, 'expires_at': reset_token.expires_at.isoformat()}
        if settings.DEBUG:
            response_data['reset_token'] = reset_token.token
            response_data['reset_url'] = reset_path
        return Response(response_data)


class ResetPasswordView(APIView):
    """使用重置令牌设置新密码

    双轨开关: PASSWORD_SELF_SERVICE_ENABLED=False 时密码自助服务下线 (R14)。
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not getattr(settings, 'PASSWORD_SELF_SERVICE_ENABLED', True):
            return _feature_disabled_response('密码自助服务已关闭，请在统一身份平台自助重置密码')
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_str = serializer.validated_data['token']

        try:
            reset_token = PasswordResetToken.objects.select_related('employee').get(token=token_str)
        except PasswordResetToken.DoesNotExist:
            return Response({'detail': '无效的重置链接'}, status=status.HTTP_400_BAD_REQUEST)

        if not reset_token.is_valid:
            return Response({'detail': '重置链接已过期或已使用'}, status=status.HTTP_400_BAD_REQUEST)

        employee = reset_token.employee
        employee.set_password(serializer.validated_data['new_password'])
        employee.must_change_password = False
        employee.save(update_fields=['password', 'must_change_password', 'updated_at'])
        reset_token.used = True
        reset_token.save(update_fields=['used'])
        AuthToken.objects.filter(employee=employee).delete()
        return Response({'detail': '密码重置成功，请使用新密码登录'})
