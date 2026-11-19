# -*- coding: utf-8 -*-
"""更新 BudgetBol 唯一索引：增加 process_type_details 列"""
from django.db import migrations


def recreate_unique_index(apps, schema_editor):
    """删除旧唯一索引，创建新唯一索引（包含 process_type_details）"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        # 1. 删除所有可能的旧唯一索引
        old_index_names = [
            'CN_IE_BOL_BudgetBol_fiscal_year_bol_type_program_code_process_line_nr_version_e151d040_uniq',
            'CN_IE_BOL_BudgetBol_fiscal_year_bol_type_program_code_process_process_type_details_line_nr_version_515e3a82_uniq',
        ]
        for idx_name in old_index_names:
            try:
                cursor.execute(
                    f"IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{idx_name}' "
                    f"AND object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol')) "
                    f"DROP INDEX [{idx_name}] ON [db_datawriter].[CN_IE_BOL_BudgetBol]"
                )
            except Exception:
                pass

        # 2. 创建新的唯一索引（包含 process_type_details）
        new_idx_name = 'CN_IE_BOL_BudgetBol_uniq_new'
        try:
            cursor.execute(
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{new_idx_name}' "
                f"AND object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_BudgetBol')) "
                f"CREATE UNIQUE INDEX [{new_idx_name}] ON [db_datawriter].[CN_IE_BOL_BudgetBol] "
                f"(fiscal_year, bol_type, program_code, process, process_type_details, line_nr, version)"
            )
        except Exception as e:
            print(f"创建新索引失败: {e}")


def do_nothing(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('budget_bol', '0004_add_process_type_details'),
    ]

    operations = [
        # 全部用原生 SQL 处理索引，跳过 Django 的 AlterUniqueTogether
        migrations.RunPython(recreate_unique_index, do_nothing),
    ]