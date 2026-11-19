# -*- coding: utf-8 -*-
"""同步 Django 状态（数据库已通过 0006 迁移创建好，这里仅同步状态）

0006 迁移使用了原生 SQL 创建表，Django 状态和模型定义有细微差异
（verbose_name / help_text 等元数据），本迁移将这些差异同步到 Django 状态。
由于数据库已经按所需结构创建完成，所有操作均使用 SeparateDatabaseAndState
的 state_operations，不执行实际 SQL。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget_bol', '0006_restructure_budget_bol_tables'),
    ]

    operations = [
        # 所有 AlterField / AlterModelOptions 均为状态同步，不执行 SQL
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelOptions(
                    name='achievabletargetbol',
                    options={'managed': True, 'ordering': ['-fiscal_year', 'project_code', 'process_type'], 'verbose_name': 'Achievable/Target BOL', 'verbose_name_plural': 'Achievable/Target BOL'},
                ),
                migrations.AlterModelOptions(
                    name='budgetbol',
                    options={'managed': True, 'ordering': ['-fiscal_year', 'project_code', 'process_type'], 'verbose_name': 'Budget BOL（预算BOL）', 'verbose_name_plural': 'Budget BOL（预算BOL）'},
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='asset',
                    field=models.CharField(blank=True, default='', help_text='Excel 第3列 Asset', max_length=30, verbose_name='产线编号'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='bol',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 最后一列 BOL(mins) 或 BOL(minutes)', max_digits=12, null=True, verbose_name='BOL值(分钟)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='bol_base',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel BOL Base 列', max_digits=12, null=True, verbose_name='BOL基准'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='bol_type',
                    field=models.CharField(choices=[('ACHIEVABLE', '可达 BOL（CT/HC 计算）'), ('TARGET', '目标 BOL（产能规划）')], max_length=20, verbose_name='BOL类型'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='comment1',
                    field=models.CharField(blank=True, default='', help_text='Excel 第7列', max_length=200, verbose_name='工艺1 备注'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='comment2',
                    field=models.CharField(blank=True, default='', help_text='Excel 第10列', max_length=200, verbose_name='工艺2 备注'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='comment3',
                    field=models.CharField(blank=True, default='', help_text='Excel 第13列', max_length=200, verbose_name='工艺3 备注'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='comment4',
                    field=models.CharField(blank=True, default='', help_text='Excel 第16列', max_length=200, verbose_name='工艺4 备注'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='comment5',
                    field=models.CharField(blank=True, default='', help_text='Excel 第19列', max_length=200, verbose_name='工艺5 备注'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='created_at',
                    field=models.DateTimeField(auto_now_add=True, verbose_name='创建时间'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='created_by',
                    field=models.CharField(blank=True, default='', max_length=50, verbose_name='创建人'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='oee',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第20列(Achievable) 或 第22列(Target)', max_digits=6, null=True, verbose_name='OEE'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='plant',
                    field=models.CharField(blank=True, default='', help_text='Excel 第4列 Plant（原值直接存储）', max_length=30, verbose_name='工厂'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process1_ct',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第5列', max_digits=12, null=True, verbose_name='工艺1 CT(秒)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process1_hc',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第6列', max_digits=10, null=True, verbose_name='工艺1 HC'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process2_ct',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第8列', max_digits=12, null=True, verbose_name='工艺2 CT(秒)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process2_hc',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第9列', max_digits=10, null=True, verbose_name='工艺2 HC'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process3_ct',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第11列', max_digits=12, null=True, verbose_name='工艺3 CT(秒)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process3_hc',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第12列', max_digits=10, null=True, verbose_name='工艺3 HC'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process4_ct',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第14列', max_digits=12, null=True, verbose_name='工艺4 CT(秒)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process4_hc',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第15列', max_digits=10, null=True, verbose_name='工艺4 HC'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process5_ct',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第17列', max_digits=12, null=True, verbose_name='工艺5 CT(秒)'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process5_hc',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第18列', max_digits=10, null=True, verbose_name='工艺5 HC'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='process_type',
                    field=models.CharField(blank=True, default='', help_text='Excel 第1列 Process Type（FA/IHR/IHE 等）', max_length=30, verbose_name='工艺类型'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='project_code',
                    field=models.CharField(help_text='Excel 第2列 Project Code', max_length=30, verbose_name='项目代码'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='updated_at',
                    field=models.DateTimeField(auto_now=True, verbose_name='更新时间'),
                ),
                migrations.AlterField(
                    model_name='achievabletargetbol',
                    name='uplift_indirect_hours',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel Uplift Indirect Hours 列', max_digits=10, null=True, verbose_name='间接工时系数'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='achievable_bol',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第6列 Achievable BOL', max_digits=12, null=True, verbose_name='可达BOL(参考)'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='ame_target_bol',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第5列 AME Target BOL', max_digits=12, null=True, verbose_name='AME目标BOL'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='asset',
                    field=models.CharField(blank=True, default='', help_text='Excel 第3列 Asset', max_length=30, verbose_name='产线编号'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='bol_type',
                    field=models.CharField(choices=[('BUDGET', '预算 BOL（直接给定值）')], default='BUDGET', max_length=20, verbose_name='BOL类型'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='budget_bol',
                    field=models.DecimalField(blank=True, decimal_places=4, help_text='Excel 第7列 Budget BOL', max_digits=12, null=True, verbose_name='预算BOL'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='created_at',
                    field=models.DateTimeField(auto_now_add=True, verbose_name='创建时间'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='created_by',
                    field=models.CharField(blank=True, default='', max_length=50, verbose_name='创建人'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='plant',
                    field=models.CharField(blank=True, default='', help_text='Excel 第4列 Plant（原值直接存储）', max_length=30, verbose_name='工厂'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='process_type',
                    field=models.CharField(blank=True, default='', help_text='Excel 第1列 Process Type（FA/IHR/IHE 等）', max_length=30, verbose_name='工艺类型'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='project_code',
                    field=models.CharField(help_text='Excel 第2列 Project Code', max_length=30, verbose_name='项目代码'),
                ),
                migrations.AlterField(
                    model_name='budgetbol',
                    name='updated_at',
                    field=models.DateTimeField(auto_now=True, verbose_name='更新时间'),
                ),
            ],
            database_operations=[],
        ),
    ]
