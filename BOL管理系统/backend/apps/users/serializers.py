# -*- coding: utf-8 -*-
"""人员管理 序列化器"""
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.users.models import Employee


class EmployeeSerializer(serializers.ModelSerializer):
    """员工序列化器"""
    display_name = serializers.CharField(read_only=True)
    role_display = serializers.CharField(read_only=True)
    has_password = serializers.BooleanField(read_only=True)
    must_change_password = serializers.BooleanField(read_only=True)
    initial_password = serializers.CharField(
        write_only=True, required=False, min_length=8
    )

    class Meta:
        model = Employee
        fields = [
            'id', 'name', 'username', 'email', 'phone', 'department', 'title',
            'role', 'role_display', 'status', 'remark', 'display_name', 'has_password',
            'must_change_password', 'initial_password', 'last_login', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_login', 'has_password']

    def validate_initial_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('initial_password'):
            raise serializers.ValidationError({
                'initial_password': '创建用户时必须设置初始密码'
            })
        return attrs

    def create(self, validated_data):
        initial_password = validated_data.pop('initial_password')
        employee = Employee(**validated_data)
        employee.set_password(initial_password)
        employee.must_change_password = True
        employee.save()
        return employee

    def update(self, instance, validated_data):
        initial_password = validated_data.pop('initial_password', None)
        if initial_password:
            instance.set_password(initial_password)
            instance.must_change_password = True
        return super().update(instance, validated_data)
