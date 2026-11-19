# -*- coding: utf-8 -*-
"""将 Employee.employee_id 重命名为 Employee.username"""
from django.db import migrations, models


def rename_field_sql_server(apps, schema_editor):
    """在 SQL Server 上重命名列 employee_id → username"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        # 先检查是否已存在 username 列（避免重复执行）
        cursor.execute(
            "SELECT COUNT(*) FROM sys.columns WHERE name = 'username' "
            "AND object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_Employee')"
        )
        if cursor.fetchone()[0] > 0:
            return  # username 列已存在，跳过

        # 检查 employee_id 列是否存在
        cursor.execute(
            "SELECT COUNT(*) FROM sys.columns WHERE name = 'employee_id' "
            "AND object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_Employee')"
        )
        if cursor.fetchone()[0] == 0:
            return  # employee_id 列不存在，跳过

        # 重命名列
        cursor.execute(
            "EXEC sp_rename 'db_datawriter.CN_IE_BOL_Employee.employee_id', 'username', 'COLUMN'"
        )

        # 更新列长度（employee_id 为 varchar(20)，username 需为 varchar(50)）
        cursor.execute(
            "ALTER TABLE db_datawriter.CN_IE_BOL_Employee ALTER COLUMN username NVARCHAR(50) NOT NULL"
        )


def rename_back_sql_server(apps, schema_editor):
    """回滚：将 username 重命名回 employee_id"""
    if schema_editor.connection.vendor != 'microsoft':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM sys.columns WHERE name = 'employee_id' "
            "AND object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_Employee')"
        )
        if cursor.fetchone()[0] > 0:
            return
        cursor.execute(
            "EXEC sp_rename 'db_datawriter.CN_IE_BOL_Employee.username', 'employee_id', 'COLUMN'"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_auth_fields'),
    ]

    operations = [
        # 使用原生 SQL 完成所有数据库变更
        migrations.RunPython(rename_field_sql_server, rename_back_sql_server),
        # 仅同步 Django 内部状态，state_operations 告诉 Django 模型状态已变更
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name='employee',
                    old_name='employee_id',
                    new_name='username',
                ),
                migrations.AlterField(
                    model_name='employee',
                    name='username',
                    field=models.CharField(
                        max_length=50, unique=True, verbose_name='用户名',
                        help_text='登录用户名，全系统唯一',
                    ),
                ),
                migrations.AlterModelOptions(
                    name='employee',
                    options={'ordering': ['username']},
                ),
            ],
            database_operations=[],  # 数据库操作已由 RunPython 完成
        ),
    ]