# -*- coding: utf-8 -*-
"""人员管理模型 - CMC库可读写"""
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class Employee(models.Model):
    """
    员工/改善责任人（CMC 读写，对应 CN_IE_BOL_Employee）
    用于高BOL跟踪任务分派与改善闭环管理
    """
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=50, verbose_name='姓名')
    username = models.CharField(
        max_length=50, unique=True, verbose_name='用户名',
        help_text='登录用户名，全系统唯一',
    )
    email = models.EmailField(blank=True, verbose_name='邮箱')
    phone = models.CharField(max_length=30, blank=True, verbose_name='电话')
    department = models.CharField(max_length=80, blank=True, verbose_name='部门')
    title = models.CharField(max_length=80, blank=True, verbose_name='职位')
    role = models.CharField(
        max_length=20, default='ENGINEER', verbose_name='角色',
        choices=[
            ('ADMIN', '系统管理员'),
            ('IE', 'IE 工程师'),
            ('MGR', '部门经理'),
            ('ENGINEER', '工程师'),
            ('VIEWER', '只读用户'),
            ('GUEST', '游客'),
        ],
    )
    status = models.CharField(
        max_length=10, default='ACTIVE', verbose_name='状态',
        choices=[
            ('ACTIVE', '在职'),
            ('INACTIVE', '停用'),
        ],
    )
    remark = models.TextField(blank=True, verbose_name='备注')
    password = models.CharField(max_length=128, blank=True, verbose_name='密码哈希')
    must_change_password = models.BooleanField(
        default=False, verbose_name='首次登录需修改密码'
    )
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        managed = True
        db_table = 'CN_IE_BOL_Employee'
        app_label = 'users'
        verbose_name = '员工'
        verbose_name_plural = verbose_name
        ordering = ['username']
        indexes = [
            models.Index(fields=['department']),
            models.Index(fields=['status']),
            models.Index(fields=['role']),
        ]

    def __str__(self):
        return f"{self.username} {self.name}"

    @property
    def display_name(self):
        """在跟踪任务分派等下拉框中显示的格式：用户名 + 姓名"""
        return f"{self.username} {self.name}"

    @property
    def role_display(self):
        return dict(self._meta.get_field('role').choices).get(self.role, self.role)

    @property
    def has_password(self):
        return bool(self.password)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        if not self.password:
            return False
        return check_password(raw_password, self.password)


class AuthToken(models.Model):
    """登录会话令牌"""
    key = models.CharField(max_length=64, primary_key=True)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='auth_tokens',
        verbose_name='员工',
    )
    source = models.CharField(
        max_length=8, default='local', verbose_name='来源',
        choices=[
            ('local', '本地登录'),
            ('oidc', '统一身份登录'),
        ],
        help_text='local=本地账密登录签发; oidc=统一身份登录(Keycloak)签发; '
                  '切换日 DELETE source=local 作废旧本地令牌 (方案文档 6.2)',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    expires_at = models.DateTimeField(verbose_name='过期时间')

    class Meta:
        db_table = 'CN_IE_BOL_AuthToken'
        app_label = 'users'
        verbose_name = '登录令牌'
        verbose_name_plural = verbose_name

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @classmethod
    def create_for_employee(cls, employee, expire_hours=168, source='local'):
        """创建令牌，默认有效期 7 天

        策略：支持多端保持登录。若该员工已有未过期的有效令牌，则复用之，
        避免每次登录都使其他端的令牌失效（"保持登录"功能依赖此行为）。
        过期令牌会被清理以控制数据库体积。

        Args:
            employee: 员工对象
            expire_hours: 有效期 (小时)
            source: 令牌来源 ('local' 本地登录 / 'oidc' 统一身份登录)。
                OIDC 登录复用本地令牌时同步来源标记 (切换日 DELETE source='local' 作废旧令牌)。
        """
        # 清理该员工已过期的令牌（不影响其他有效令牌）
        cls.objects.filter(employee=employee, expires_at__lt=timezone.now()).delete()
        # 复用现有的有效令牌（同一员工同一会话不必每次新建）
        existing = cls.objects.filter(
            employee=employee, expires_at__gte=timezone.now()
        ).order_by('-created_at').first()
        if existing:
            # OIDC 复用本地令牌时同步来源标记，保证切换日 DELETE source='local' 不漏清
            if existing.source != source:
                existing.source = source
                existing.save(update_fields=['source'])
            return existing
        # 无有效令牌时创建新令牌
        key = secrets.token_hex(32)
        expires_at = timezone.now() + timedelta(hours=expire_hours)
        return cls.objects.create(
            key=key, employee=employee, expires_at=expires_at, source=source
        )


class PasswordResetToken(models.Model):
    """忘记密码重置令牌"""
    token = models.CharField(max_length=64, unique=True, verbose_name='重置令牌')
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='reset_tokens',
        verbose_name='员工',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    expires_at = models.DateTimeField(verbose_name='过期时间')
    used = models.BooleanField(default=False, verbose_name='已使用')

    class Meta:
        db_table = 'CN_IE_BOL_PasswordResetToken'
        app_label = 'users'
        verbose_name = '密码重置令牌'
        verbose_name_plural = verbose_name

    @property
    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at

    @classmethod
    def create_for_employee(cls, employee, expire_hours=1):
        cls.objects.filter(employee=employee, used=False).update(used=True)
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(hours=expire_hours)
        return cls.objects.create(token=token, employee=employee, expires_at=expires_at)
