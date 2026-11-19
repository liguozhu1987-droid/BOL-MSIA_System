"""迁移脚本: 为 CheckItem 表添加 IsActive 字段 (审核条款启用/停用开关)

由于 SQLAlchemy create_all() 不会修改已有表结构,
需要手动 ALTER TABLE 添加新列。

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_add_checkitem_isactive
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402


TABLE = "CN_AME_MISA_CheckItem"
COLUMN = "IsActive"


def column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = :table AND COLUMN_NAME = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() > 0


def migrate() -> None:
    print(f"[migrate] 开始迁移: 为 {TABLE} 表添加 {COLUMN} 字段")
    with engine.begin() as conn:
        if column_exists(conn, TABLE, COLUMN):
            print(f"[migrate] 跳过 (已存在): {TABLE}.{COLUMN}")
            return
        sql = (
            f"ALTER TABLE [{TABLE}] ADD [{COLUMN}] "
            "BIT NOT NULL DEFAULT 1"
        )
        print(f"[migrate] 执行: {sql}")
        try:
            conn.execute(text(sql))
            print(f"[migrate] 成功: {TABLE}.{COLUMN}")
        except Exception as exc:
            print(f"[migrate] 失败: {TABLE}.{COLUMN}: {exc}")
            raise

    # 同时回填 PhaseReviewItem 不需要, 因为停用只影响 CheckItem 查询
    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
