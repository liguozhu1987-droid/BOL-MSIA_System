# -*- coding: utf-8 -*-
"""发送改善机会分析周报到管理员邮箱"""
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from apps.analytics.report_generator import generate_improvement_report_html
import datetime


class Command(BaseCommand):
    help = '发送改善机会分析周报到管理员邮箱'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            default='',
            help='指定接收邮箱（覆盖 settings.ADMIN_EMAIL），多个用逗号分隔'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅生成报告打印到控制台，不发送邮件'
        )

    def handle(self, *args, **options):
        # 生成 HTML 报告
        html_content = generate_improvement_report_html()

        if options['dry_run']:
            self.stdout.write(html_content)
            return

        # 获取收件人
        admin_email = options['email'] or getattr(settings, 'ADMIN_EMAIL', '')
        if not admin_email:
            self.stderr.write(self.style.ERROR(
                '未配置管理员邮箱，请在 db_config.ini [email] admin_email 中设置，或使用 --email 参数'
            ))
            return

        recipients = [e.strip() for e in admin_email.split(',') if e.strip()]

        subject = f'BOL管理系统 - 改善机会分析周报 ({datetime.date.today().strftime("%Y-%m-%d")})'
        from_email = settings.DEFAULT_FROM_EMAIL

        msg = EmailMultiAlternatives(
            subject=subject,
            body='本邮件为 HTML 格式，请使用支持 HTML 的邮件客户端查看。',
            from_email=from_email,
            to=recipients,
        )
        msg.attach_alternative(html_content, 'text/html')

        try:
            msg.send()
            self.stdout.write(self.style.SUCCESS(
                f'改善机会分析周报已发送至: {", ".join(recipients)}'
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'邮件发送失败: {e}'))
