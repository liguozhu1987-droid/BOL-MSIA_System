# -*- coding: utf-8 -*-
"""移除 BudgetBol 和 AchievableTargetBol 表的唯一约束

按用户要求"导入前无需与任何表内容检索查询"，每行 Excel 都应直接导入。
如果 Excel 中存在重复的 (project_code, process_type, asset) 行，唯一约束会阻止导入。
导入逻辑采用"先清空再全量导入"，不需要唯一约束防止重复。
"""
from django.db import migrations


def drop_unique_constraints(apps, schema_editor):
    """删除两个表上的唯一约束（通过 ALTER TABLE DROP CONSTRAINT）"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        # 删除 CN_IE_BOL_BudgetBol 表的唯一约束
        try:
            cursor.execute("""
                IF EXISTS (SELECT 1 FROM sys.key_constraints
                           WHERE type = 'UQ'
                           AND name = 'CN_IE_BOL_BudgetBol_uniq'
                           AND parent_object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol'))
                    ALTER TABLE [db_datawriter].[CN_IE_BOL_BudgetBol] DROP CONSTRAINT [CN_IE_BOL_BudgetBol_uniq]
            """)
        except Exception as e:
            print(f"删除 CN_IE_BOL_BudgetBol_uniq 失败（可忽略）: {e}")

        # 删除 CN_IE_BOL_AchievableTargetBol 表的唯一约束
        try:
            cursor.execute("""
                IF EXISTS (SELECT 1 FROM sys.key_constraints
                           WHERE type = 'UQ'
                           AND name = 'CN_IE_BOL_AchievableTargetBol_uniq'
                           AND parent_object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_AchievableTargetBol'))
                    ALTER TABLE [db_datawriter].[CN_IE_BOL_AchievableTargetBol] DROP CONSTRAINT [CN_IE_BOL_AchievableTargetBol_uniq]
            """)
        except Exception as e:
            print(f"删除 CN_IE_BOL_AchievableTargetBol_uniq 失败（可忽略）: {e}")


def do_nothing(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('budget_bol', '0007_sync_state_after_restructure'),
    ]

    operations = [
        # 用 SeparateDatabaseAndState：数据库由原生 SQL 处理，Django 状态用 AlterUniqueTogether 同步
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(
                    name='achievabletargetbol',
                    unique_together=set(),
                ),
                migrations.AlterUniqueTogether(
                    name='budgetbol',
                    unique_together=set(),
                ),
            ],
            database_operations=[
                migrations.RunPython(drop_unique_constraints, do_nothing),
            ],
        ),
    ]
