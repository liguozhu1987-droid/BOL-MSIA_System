"""迁移: Issue 表增加评分管控字段

新增列:
- ScoreAtClosure   整改前评分 (批准关闭时快照)
- ScoreAfterUpdate  整改后评分 (关闭后重新评分回写)
- ScoreUpdatedAt    整改后评分更新时间

运行: C:\\python\\python.exe -X utf8 -m app.scripts.migrate_issue_score_control
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
    ("ScoreAtClosure", "NUMERIC(5,2) NULL"),
    ("ScoreAfterUpdate", "NUMERIC(5,2) NULL"),
    ("ScoreUpdatedAt", "DATETIME NULL"),
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
