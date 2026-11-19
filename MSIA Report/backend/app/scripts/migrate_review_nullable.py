"""迁移: ReviewRecord 表旧外键字段改为可空

背景:
    ReviewRecord 表的 ProjectId/PhaseId/ItemId 历史上为 NOT NULL 且有外键约束,
    指向 CN_AME_MISA_Project / CN_AME_MISA_Phase / CN_AME_MISA_CheckItem.
    但系统改造后, 评审记录通过 PhaseReviewItemId + PlanId 关联,
    ProjectId/PhaseId/ItemId 已成为历史遗留字段.

    前端提交评审时传占位值 1, 但 Project/Phase 表为空导致 FK 约束失败 (500 错误).
    本脚本: 删除相关 FK 约束, ALTER COLUMN 允许 NULL.

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_review_nullable
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db.session import engine, SessionLocal


TABLE = "CN_AME_MISA_ReviewRecord"
# 三个旧外键列 (改为允许 NULL)
NULLABLE_COLUMNS = ["ProjectId", "PhaseId", "ItemId"]


def list_fk_constraints(db) -> list[tuple[str, str]]:
    """查询 ReviewRecord 表上所有外键约束 (约束名, 引用表名)"""
    sql = text(
        """
        SELECT fk.name AS constraint_name,
               OBJECT_NAME(fk.referenced_object_id) AS ref_table
        FROM sys.foreign_keys fk
        WHERE fk.parent_object_id = OBJECT_ID(:table_name)
        """
    )
    result = db.execute(sql, {"table_name": TABLE})
    return [(row[0], row[1]) for row in result]


def main():
    db = SessionLocal()
    try:
        # 1. 列出当前所有 FK 约束
        fks = list_fk_constraints(db)
        print(f"[migrate] {TABLE} 表当前外键约束:")
        for name, ref_table in fks:
            print(f"  - {name} -> {ref_table}")

        # 2. 删除所有指向 Project/Phase/CheckItem 的外键约束
        drop_targets = {"CN_AME_MISA_Project", "CN_AME_MISA_Phase", "CN_AME_MISA_CheckItem"}
        for name, ref_table in fks:
            if ref_table in drop_targets:
                print(f"[migrate] DROP CONSTRAINT: {name} (-> {ref_table})")
                db.execute(text(f"ALTER TABLE [{TABLE}] DROP CONSTRAINT [{name}]"))

        # 3. ALTER COLUMN 允许 NULL
        for col in NULLABLE_COLUMNS:
            print(f"[migrate] ALTER COLUMN {col} -> NULL")
            db.execute(text(f"ALTER TABLE [{TABLE}] ALTER COLUMN [{col}] BIGINT NULL"))

        db.commit()
        print("[migrate] 提交完成")

        # 4. 验证
        remaining_fks = list_fk_constraints(db)
        print(f"\n[migrate] 验证: 剩余外键约束 {len(remaining_fks)} 个:")
        for name, ref_table in remaining_fks:
            print(f"  - {name} -> {ref_table}")

    except Exception as e:
        db.rollback()
        print(f"[migrate] 失败: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
