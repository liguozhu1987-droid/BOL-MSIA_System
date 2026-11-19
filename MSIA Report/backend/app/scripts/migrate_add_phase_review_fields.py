"""迁移脚本: 为 ReviewRecord 和 Issue 表添加新字段

由于 SQLAlchemy create_all() 不会修改已有表结构,
需要手动 ALTER TABLE 添加新列.

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_add_phase_review_fields
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402


# 需要添加的列 (表名, 列名, 列定义)
NEW_COLUMNS = [
    # ReviewRecord 新增字段
    ("CN_AME_MISA_ReviewRecord", "PhaseReviewItemId", "BIGINT NULL"),
    ("CN_AME_MISA_ReviewRecord", "PhaseCode", "NVARCHAR(20) NULL"),
    ("CN_AME_MISA_ReviewRecord", "ItemNo", "NVARCHAR(50) NULL"),
    # Issue 新增字段
    ("CN_AME_MISA_Issue", "PhaseReviewItemId", "BIGINT NULL"),
    ("CN_AME_MISA_Issue", "PlanId", "NVARCHAR(100) NULL"),
    ("CN_AME_MISA_Issue", "PhaseCode", "NVARCHAR(20) NULL"),
    ("CN_AME_MISA_Issue", "ItemNo", "NVARCHAR(50) NULL"),
    ("CN_AME_MISA_Issue", "OwnerName", "NVARCHAR(100) NULL"),
    ("CN_AME_MISA_Issue", "Severity", "NVARCHAR(2) NOT NULL DEFAULT 'M'"),
    # ProjectId 改为可空 (SQL Server 不能直接 ALTER, 需要先检查约束)
    # 这里不修改 ProjectId 的 nullable, 保持向后兼容
]


def column_exists(conn, table: str, column: str) -> bool:
    """检查列是否已存在"""
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = :table AND COLUMN_NAME = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() > 0


def migrate() -> None:
    print("[migrate] 开始迁移: 添加新字段到 ReviewRecord 和 Issue 表")
    with engine.begin() as conn:
        for table, column, col_def in NEW_COLUMNS:
            if column_exists(conn, table, column):
                print(f"[migrate] 跳过 (已存在): {table}.{column}")
                continue
            sql = f"ALTER TABLE [{table}] ADD [{column}] {col_def}"
            print(f"[migrate] 执行: {sql}")
            try:
                conn.execute(text(sql))
                print(f"[migrate] 成功: {table}.{column}")
            except Exception as exc:
                print(f"[migrate] 失败: {table}.{column}: {exc}")
                # 继续执行其他列
                continue

    # 创建索引 (如果不存在)
    with engine.begin() as conn:
        for table, column in [
            ("CN_AME_MISA_ReviewRecord", "PhaseReviewItemId"),
            ("CN_AME_MISA_ReviewRecord", "PhaseCode"),
            ("CN_AME_MISA_ReviewRecord", "ItemNo"),
            ("CN_AME_MISA_Issue", "PhaseReviewItemId"),
            ("CN_AME_MISA_Issue", "PlanId"),
            ("CN_AME_MISA_Issue", "PhaseCode"),
            ("CN_AME_MISA_Issue", "ItemNo"),
            ("CN_AME_MISA_Issue", "Severity"),
        ]:
            idx_name = f"IX_{table}_{column}"
            # 检查索引是否已存在
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM sys.indexes "
                    "WHERE name = :idx_name AND object_id = OBJECT_ID(:table)"
                ),
                {"idx_name": idx_name, "table": f"[{table}]"},
            )
            if result.scalar() > 0:
                print(f"[migrate] 索引已存在: {idx_name}")
                continue
            sql = f"CREATE INDEX [{idx_name}] ON [{table}] ([{column}])"
            print(f"[migrate] 创建索引: {sql}")
            try:
                conn.execute(text(sql))
                print(f"[migrate] 索引创建成功: {idx_name}")
            except Exception as exc:
                print(f"[migrate] 索引创建失败: {idx_name}: {exc}")

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
