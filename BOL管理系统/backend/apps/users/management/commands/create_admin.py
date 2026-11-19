# -*- coding: utf-8 -*-
"""创建初始管理员账号"""
from django.core.management.base import BaseCommand

from apps.users.models import Employee


class Command(BaseCommand):
    help = '创建系统管理员账号（用户名 admin）'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin', help='管理员用户名')
        parser.add_argument('--name', default='系统管理员', help='姓名')
        parser.add_argument('--email', default='admin@bol.local', help='邮箱')
        parser.add_argument('--password', default='Admin@123456', help='初始密码')

    def handle(self, *args, **options):
        username = options['username']
        if Employee.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'用户名 {username} 已存在，跳过创建'))
            return

        employee = Employee(
            username=username,
            name=options['name'],
            email=options['email'],
            role='ADMIN',
            status='ACTIVE',
        )
        employee.set_password(options['password'])
        employee.save()
        self.stdout.write(self.style.SUCCESS(
            f'管理员已创建：用户名={username}，密码={options["password"]}'
        ))