# -*- coding: utf-8 -*-
"""认证相关序列化器"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.users.models import Employee


class EmployeeProfileSerializer(serializers.ModelSerializer):
    """当前登录用户信息（不含密码）"""
    display_name = serializers.CharField(read_only=True)
    role_display = serializers.CharField(read_only=True)
    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = Employee
        fields = [
            'id', 'username', 'name', 'email', 'phone',
            'department', 'title', 'role', 'role_display', 'status',
            'display_name', 'has_password', 'must_change_password', 'last_login', 'created_at',
        ]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=50)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    password_confirm = serializers.CharField(write_only=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    department = serializers.CharField(max_length=80, required=False, allow_blank=True)
    title = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate_username(self, value):
        if Employee.objects.filter(username=value).exists():
            raise serializers.ValidationError('该用户名已注册')
        return value.strip()

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': '两次输入的密码不一致'})
        try:
            validate_password(attrs['password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        employee = Employee(
            role='VIEWER',
            status='ACTIVE',
            **validated_data,
        )
        employee.set_password(password)
        employee.save()
        return employee


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs['username'].strip()
        try:
            employee = Employee.objects.get(username=username)
        except Employee.DoesNotExist:
            raise serializers.ValidationError('用户名或密码错误')

        if employee.status != 'ACTIVE':
            raise serializers.ValidationError('账号已停用，请联系管理员')

        if not employee.check_password(attrs['password']):
            raise serializers.ValidationError('用户名或密码错误')

        attrs['employee'] = employee
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=8, write_only=True)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': '两次输入的新密码不一致'})
        try:
            validate_password(attrs['new_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})
        return attrs

    def validate_old_password(self, value):
        employee = self.context['employee']
        if not employee.check_password(value):
            raise serializers.ValidationError('原密码不正确')
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50)
    email = serializers.EmailField()

    def validate(self, attrs):
        username = attrs['username'].strip()
        email = attrs['email'].strip().lower()
        try:
            employee = Employee.objects.get(username=username)
        except Employee.DoesNotExist:
            raise serializers.ValidationError('用户名与邮箱不匹配')

        if employee.email.lower() != email:
            raise serializers.ValidationError('用户名与邮箱不匹配')

        if not employee.has_password:
            raise serializers.ValidationError('该账号尚未设置密码，请先注册')

        attrs['employee'] = employee
        return attrs


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': '两次输入的密码不一致'})
        try:
            validate_password(attrs['new_password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})
        return attrs