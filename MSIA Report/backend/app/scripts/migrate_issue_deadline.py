"""迁移: Issue 表增加 Deadline (整改完成日期) 字段

新增列:
- Deadline          整改完成日期 (默认=阶段实际审核完成日期+10自然日, 逾期判定硬边界)
- DeadlineIsManual  Deadline 是否被人工修改 (人工修改后不再被自动回填覆盖)

运行: python -X utf8 -m app.scripts.migrate_issue_deadline
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

COLUMNS = [
    ("Deadline", "DATETIME NULL"),
    ("DeadlineIsManual", "BIT NOT NULL CONSTRAINT DF_Issue_DeadlineIsManual DEFAULT (0)"),
]


def main() -> None:
    with engine.begin() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'CN_AME_MISA_Issue'")
            )
        }
        for name, ddl in COLUMNS:
            if name in existing:
                print(f"[skip] 列已存在: {name}")
                continue
            conn.execute(text(f"ALTER TABLE CN_AME_MISA_Issue ADD {name} {ddl}"))
            print(f"[ok] 新增列: {name} {ddl}")
    print("迁移完成")


if __name__ == "__main__":
    main()
