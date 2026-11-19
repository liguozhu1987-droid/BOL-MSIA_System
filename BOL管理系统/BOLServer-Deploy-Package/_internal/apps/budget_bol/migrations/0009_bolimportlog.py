# -*- coding: utf-8 -*-
"""新增预算 BOL 导入履历表 BolImportLog

记录每次 Excel 导入的时间、文件名、BOL 类型、导入用户及行数统计，
用于在导入弹窗中查看导入履历。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget_bol', '0008_remove_unique_constraints'),
    ]

    operations = [
        migrations.CreateModel(
            name='BolImportLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True)),
                ('fiscal_year', models.IntegerField(verbose_name='财年')),
                ('bol_type', models.CharField(help_text='BUDGET / ACHIEVABLE / TARGET',
                                              max_length=20, verbose_name='BOL类型')),
                ('file_name', models.CharField(blank=True, default='',
                                               max_length=255, verbose_name='导入文件名')),
                ('file_size', models.BigIntegerField(blank=True, null=True,
                                                    verbose_name='文件大小(字节)')),
                ('total_rows', models.IntegerField(default=0, verbose_name='Excel总行数')),
                ('imported', models.IntegerField(default=0, verbose_name='成功导入行数')),
                ('skipped', models.IntegerField(default=0, verbose_name='跳过行数')),
                ('deleted', models.IntegerField(default=0, verbose_name='删除旧数据行数')),
                ('status', models.CharField(choices=[
                    ('SUCCESS', '导入成功'),
                    ('FAILED', '导入失败'),
                ], max_length=10, verbose_name='导入状态')),
                ('error_message', models.TextField(blank=True, default='',
                                                   verbose_name='失败原因')),
                ('imported_by', models.CharField(blank=True, default='', max_length=50,
                                                 verbose_name='导入用户')),
                ('created_at', models.DateTimeField(auto_now_add=True,
                                                    verbose_name='导入时间')),
            ],
            options={
                'verbose_name': '预算BOL导入履历',
                'verbose_name_plural': '预算BOL导入履历',
                'db_table': 'CN_IE_BOL_ImportLog',
                'ordering': ['-created_at'],
            },
        ),
    ]
