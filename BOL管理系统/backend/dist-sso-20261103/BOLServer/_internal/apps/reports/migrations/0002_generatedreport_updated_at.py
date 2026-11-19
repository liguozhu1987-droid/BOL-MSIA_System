# -*- coding: utf-8 -*-
"""新增 updated_at（最近生成时间）：

同周期报告重新生成时 update_or_create 原地替换，created_at（auto_now_add）
不会刷新，导致列表"生成时间"停留在首次生成日。回填 updated_at = created_at，
此后每次重新生成由 auto_now 自动刷新。
"""
import django.utils.timezone
from django.db import migrations, models


def backfill_updated_at(apps, schema_editor):
    """存量行：updated_at 回填为 created_at（首次生成时间）"""
    GeneratedReport = apps.get_model('reports', 'GeneratedReport')
    GeneratedReport.objects.update(updated_at=models.F('created_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='generatedreport',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='最近生成时间'),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
    ]
