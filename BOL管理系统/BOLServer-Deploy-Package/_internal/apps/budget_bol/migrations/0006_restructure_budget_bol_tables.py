# -*- coding: utf-8 -*-
"""重构 BudgetBol 表结构（7列对应 Excel）+ 新增 AchievableTargetBol 表（23列对应 Excel）

按用户要求重构表结构：
1. 删除旧表 CN_IE_BOL_BudgetBol（含旧字段 process/location/ct/hc/oee/bol 等）
2. 创建新表 CN_IE_BOL_BudgetBol（仅7列对应 Excel "2026 Budget BOL" sheet）
3. 创建新表 CN_IE_BOL_AchievableTargetBol（23列对应 Excel "2026 Achievable/Target BOL" sheet）

旧数据无法保留（字段语义全部变化），用户需重新导入 Excel。
"""
from django.db import migrations, models


# SQL Server 表结构定义
DROP_OLD_BUDGETBOL_TABLE = """
IF OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol', 'U') IS NOT NULL
    DROP TABLE [db_datawriter].[CN_IE_BOL_BudgetBol]
"""

CREATE_NEW_BUDGETBOL_TABLE = """
IF OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol', 'U') IS NULL
CREATE TABLE [db_datawriter].[CN_IE_BOL_BudgetBol] (
    [id] BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [fiscal_year] INT NOT NULL,
    [bol_type] NVARCHAR(20) NOT NULL,
    [process_type] NVARCHAR(30) NOT NULL DEFAULT '',
    [project_code] NVARCHAR(30) NOT NULL,
    [asset] NVARCHAR(30) NOT NULL DEFAULT '',
    [plant] NVARCHAR(30) NOT NULL DEFAULT '',
    [ame_target_bol] DECIMAL(12,4) NULL,
    [achievable_bol] DECIMAL(12,4) NULL,
    [budget_bol] DECIMAL(12,4) NULL,
    [created_by] NVARCHAR(50) NOT NULL DEFAULT '',
    [created_at] DATETIMEOFFSET NULL,
    [updated_at] DATETIMEOFFSET NULL,
    CONSTRAINT [CN_IE_BOL_BudgetBol_uniq] UNIQUE (
        [fiscal_year], [bol_type], [project_code], [process_type], [asset]
    )
)
"""

CREATE_NEW_ACHIEVABLETARGETBOL_TABLE = """
IF OBJECT_ID('db_datawriter.CN_IE_BOL_AchievableTargetBol', 'U') IS NULL
CREATE TABLE [db_datawriter].[CN_IE_BOL_AchievableTargetBol] (
    [id] BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [fiscal_year] INT NOT NULL,
    [bol_type] NVARCHAR(20) NOT NULL,
    [process_type] NVARCHAR(30) NOT NULL DEFAULT '',
    [project_code] NVARCHAR(30) NOT NULL,
    [asset] NVARCHAR(30) NOT NULL DEFAULT '',
    [plant] NVARCHAR(30) NOT NULL DEFAULT '',
    [process1_ct] DECIMAL(12,4) NULL,
    [process1_hc] DECIMAL(10,4) NULL,
    [comment1] NVARCHAR(200) NOT NULL DEFAULT '',
    [process2_ct] DECIMAL(12,4) NULL,
    [process2_hc] DECIMAL(10,4) NULL,
    [comment2] NVARCHAR(200) NOT NULL DEFAULT '',
    [process3_ct] DECIMAL(12,4) NULL,
    [process3_hc] DECIMAL(10,4) NULL,
    [comment3] NVARCHAR(200) NOT NULL DEFAULT '',
    [process4_ct] DECIMAL(12,4) NULL,
    [process4_hc] DECIMAL(10,4) NULL,
    [comment4] NVARCHAR(200) NOT NULL DEFAULT '',
    [process5_ct] DECIMAL(12,4) NULL,
    [process5_hc] DECIMAL(10,4) NULL,
    [comment5] NVARCHAR(200) NOT NULL DEFAULT '',
    [oee] DECIMAL(6,4) NULL,
    [bol_base] DECIMAL(12,4) NULL,
    [uplift_indirect_hours] DECIMAL(10,4) NULL,
    [bol] DECIMAL(12,4) NULL,
    [created_by] NVARCHAR(50) NOT NULL DEFAULT '',
    [created_at] DATETIMEOFFSET NULL,
    [updated_at] DATETIMEOFFSET NULL,
    CONSTRAINT [CN_IE_BOL_AchievableTargetBol_uniq] UNIQUE (
        [fiscal_year], [bol_type], [project_code], [process_type], [asset]
    )
)
"""


def drop_and_recreate_tables(apps, schema_editor):
    """删除旧表 + 创建新表"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        # 1. 删除旧 BudgetBol 表（含旧字段）
        try:
            cursor.execute(DROP_OLD_BUDGETBOL_TABLE)
        except Exception as e:
            print(f"删除旧表 CN_IE_BOL_BudgetBol 失败（可忽略）: {e}")

        # 2. 创建新 BudgetBol 表（7列结构）
        try:
            cursor.execute(CREATE_NEW_BUDGETBOL_TABLE)
        except Exception as e:
            print(f"创建新表 CN_IE_BOL_BudgetBol 失败: {e}")

        # 3. 创建新 AchievableTargetBol 表（23列结构）
        try:
            cursor.execute(CREATE_NEW_ACHIEVABLETARGETBOL_TABLE)
        except Exception as e:
            print(f"创建新表 CN_IE_BOL_AchievableTargetBol 失败: {e}")


def drop_new_tables(apps, schema_editor):
    """回滚：删除新表"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute("""
                IF OBJECT_ID('db_datawriter.CN_IE_BOL_AchievableTargetBol', 'U') IS NOT NULL
                    DROP TABLE [db_datawriter].[CN_IE_BOL_AchievableTargetBol]
            """)
        except Exception:
            pass
        try:
            cursor.execute("""
                IF OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol', 'U') IS NOT NULL
                    DROP TABLE [db_datawriter].[CN_IE_BOL_BudgetBol]
            """)
        except Exception:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ('budget_bol', '0005_alter_budgetbol_unique_together'),
    ]

    operations = [
        # 用 SeparateDatabaseAndState：数据库由原生 SQL 处理，
        # Django 状态用 DeleteModel + CreateModel 同步
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # 先删除旧 BudgetBol 模型状态
                migrations.DeleteModel(name='BudgetBol'),
                # 创建新 BudgetBol 模型状态（7列结构）
                migrations.CreateModel(
                    name='BudgetBol',
                    fields=[
                        ('id', models.BigAutoField(primary_key=True, serialize=False)),
                        ('fiscal_year', models.IntegerField(verbose_name='财年')),
                        ('bol_type', models.CharField(default='BUDGET', max_length=20, verbose_name='BOL类型')),
                        ('process_type', models.CharField(blank=True, default='', max_length=30, verbose_name='工艺类型')),
                        ('project_code', models.CharField(max_length=30, verbose_name='项目代码')),
                        ('asset', models.CharField(blank=True, default='', max_length=30, verbose_name='产线编号')),
                        ('plant', models.CharField(blank=True, default='', max_length=30, verbose_name='工厂')),
                        ('ame_target_bol', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('achievable_bol', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('budget_bol', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('created_by', models.CharField(blank=True, default='', max_length=50)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'db_table': 'CN_IE_BOL_BudgetBol',
                        'verbose_name': 'Budget BOL（预算BOL）',
                        'verbose_name_plural': 'Budget BOL（预算BOL）',
                        'unique_together': {('fiscal_year', 'bol_type', 'project_code', 'process_type', 'asset')},
                        'ordering': ['-fiscal_year', 'project_code', 'process_type'],
                    },
                ),
                # 创建 AchievableTargetBol 模型状态（23列结构）
                migrations.CreateModel(
                    name='AchievableTargetBol',
                    fields=[
                        ('id', models.BigAutoField(primary_key=True, serialize=False)),
                        ('fiscal_year', models.IntegerField(verbose_name='财年')),
                        ('bol_type', models.CharField(max_length=20, verbose_name='BOL类型')),
                        ('process_type', models.CharField(blank=True, default='', max_length=30, verbose_name='工艺类型')),
                        ('project_code', models.CharField(max_length=30, verbose_name='项目代码')),
                        ('asset', models.CharField(blank=True, default='', max_length=30, verbose_name='产线编号')),
                        ('plant', models.CharField(blank=True, default='', max_length=30, verbose_name='工厂')),
                        ('process1_ct', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('process1_hc', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('comment1', models.CharField(blank=True, default='', max_length=200)),
                        ('process2_ct', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('process2_hc', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('comment2', models.CharField(blank=True, default='', max_length=200)),
                        ('process3_ct', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('process3_hc', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('comment3', models.CharField(blank=True, default='', max_length=200)),
                        ('process4_ct', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('process4_hc', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('comment4', models.CharField(blank=True, default='', max_length=200)),
                        ('process5_ct', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('process5_hc', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('comment5', models.CharField(blank=True, default='', max_length=200)),
                        ('oee', models.DecimalField(decimal_places=4, max_digits=6, null=True, blank=True)),
                        ('bol_base', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('uplift_indirect_hours', models.DecimalField(decimal_places=4, max_digits=10, null=True, blank=True)),
                        ('bol', models.DecimalField(decimal_places=4, max_digits=12, null=True, blank=True)),
                        ('created_by', models.CharField(blank=True, default='', max_length=50)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'db_table': 'CN_IE_BOL_AchievableTargetBol',
                        'verbose_name': 'Achievable/Target BOL',
                        'verbose_name_plural': 'Achievable/Target BOL',
                        'unique_together': {('fiscal_year', 'bol_type', 'project_code', 'process_type', 'asset')},
                        'ordering': ['-fiscal_year', 'project_code', 'process_type'],
                    },
                ),
            ],
            database_operations=[
                migrations.RunPython(drop_and_recreate_tables, drop_new_tables),
            ],
        ),
    ]
