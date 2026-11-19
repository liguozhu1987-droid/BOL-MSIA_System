"""迁移脚本: 让 Issue 表的 ProjectId 列可空

Issue 表的 ProjectId 原来是 NOT NULL, 现在需要改为 NULL,
以支持通过 PlanId (字符串) 关联 MSIA 计划项目, 而非 Project 表.

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_issue_projectid_nullable
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402


def migrate() -> None:
    print("[migrate] 开始: 让 CN_AME_MISA_Issue.ProjectId 可空")
    with engine.begin() as conn:
        # 检查当前列定义
        result = conn.execute(
            text(
                "SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = 'CN_AME_MISA_Issue' AND COLUMN_NAME = 'ProjectId'"
            )
        )
        is_nullable = result.scalar()
        print(f"[migrate] 当前 ProjectId IS_NULLABLE = {is_nullable}")

        if is_nullable == "NO":
            # 先删除外键约束 (如果存在)
            # 查找 ProjectId 的外键约束名 (使用 sys.foreign_key_columns 视图)
            result = conn.execute(
                text(
                    "SELECT fk.name FROM sys.foreign_keys fk "
                    "INNER JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id "
                    "WHERE OBJECT_NAME(fk.parent_object_id) = 'CN_AME_MISA_Issue' "
                    "AND COL_NAME(fkc.parent_object_id, fkc.parent_column_id) = 'ProjectId'"
                )
            )
            fk_name = result.scalar()
            if fk_name:
                print(f"[migrate] 删除外键约束: {fk_name}")
                conn.execute(text(f"ALTER TABLE [CN_AME_MISA_Issue] DROP CONSTRAINT [{fk_name}]"))

            # 修改列为可空
            print("[migrate] 修改 ProjectId 为 NULL")
            conn.execute(
                text(
                    "ALTER TABLE [CN_AME_MISA_Issue] ALTER COLUMN [ProjectId] BIGINT NULL"
                )
            )
            print("[migrate] 成功: ProjectId 已改为可空")

            # 重新添加外键约束 (允许 NULL)
            print("[migrate] 重新添加外键约束 (允许 NULL)")
            conn.execute(
                text(
                    "ALTER TABLE [CN_AME_MISA_Issue] "
                    "ADD CONSTRAINT [FK_Issue_Project] FOREIGN KEY ([ProjectId]) "
                    "REFERENCES [CN_AME_MISA_Project] ([Id])"
                )
            )
            print("[migrate] 成功: 外键约束已添加")
        else:
            print("[migrate] 跳过: ProjectId 已经是可空的")

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
