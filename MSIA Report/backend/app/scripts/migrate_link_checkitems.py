"""迁移脚本: 审核标准条款 (CheckItem) 与阶段评审清单 (PhaseReviewItem) 联动

作用:
  1. 为 PhaseReviewItem 表添加 CheckItemId 列 (+ 索引)
  2. 存量同步: 遍历所有未删除的 CheckItem
     - 已有显式关联 (CheckItemId) → 跳过
     - 同阶段下有名称匹配的 PhaseReviewItem → 补 CheckItemId 关联 (不新建, 避免重复)
     - 无匹配 (如手工新增的 MSIA-0120) → 新建 PhaseReviewItem 条目

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.migrate_link_checkitems
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.check_item import CheckItem  # noqa: E402
from app.models.phase_review_item import PhaseReviewItem  # noqa: E402


def _normalize_name(name: str) -> str:
    """规范化名称用于匹配: 去除所有非字母数字字符, 转小写"""
    if not name:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = :table AND COLUMN_NAME = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() > 0


def migrate_schema() -> None:
    """1. 添加 CheckItemId 列与索引"""
    table = PhaseReviewItem.__tablename__
    with engine.begin() as conn:
        if not _column_exists(conn, table, "CheckItemId"):
            conn.execute(text(f"ALTER TABLE [{table}] ADD [CheckItemId] BIGINT NULL"))
            print(f"[migrate] 已添加列: {table}.CheckItemId")
        else:
            print(f"[migrate] 列已存在: {table}.CheckItemId")

        idx_name = f"IX_{table}_CheckItemId"
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM sys.indexes "
                "WHERE name = :idx_name AND object_id = OBJECT_ID(:table)"
            ),
            {"idx_name": idx_name, "table": f"[{table}]"},
        )
        if result.scalar() == 0:
            conn.execute(text(f"CREATE INDEX [{idx_name}] ON [{table}] ([CheckItemId])"))
            print(f"[migrate] 已创建索引: {idx_name}")


def sync_data() -> None:
    """2. 存量同步: CheckItem → PhaseReviewItem"""
    db = SessionLocal()
    linked = created = skipped = 0
    try:
        check_items = (
            db.query(CheckItem)
            .filter(CheckItem.IsDeleted == False)  # noqa: E712
            .order_by(CheckItem.PhaseCode, CheckItem.ItemNo)
            .all()
        )
        print(f"[migrate] 待处理审核标准条款: {len(check_items)} 条")

        for ci in check_items:
            # 2.1 已有显式关联 → 跳过
            existing = db.query(PhaseReviewItem).filter(
                PhaseReviewItem.CheckItemId == ci.Id
            ).first()
            if existing:
                skipped += 1
                continue

            # 2.2 同阶段下按名称匹配 (精确 → 规范化)
            candidates = db.query(PhaseReviewItem).filter(
                PhaseReviewItem.PhaseCode == ci.PhaseCode,
                PhaseReviewItem.IsDeleted == False,  # noqa: E712
            ).all()
            target_norm = _normalize_name(ci.Name)

            match = None
            for c in candidates:
                if c.ItemName == ci.Name:
                    match = c
                    break
            if match is None and target_norm:
                for c in candidates:
                    if _normalize_name(c.ItemName) == target_norm:
                        match = c
                        break

            if match is not None:
                # 2.2a 匹配到 → 补关联
                match.CheckItemId = ci.Id
                linked += 1
                print(f"[migrate] 关联: {ci.PhaseCode} / {ci.ItemNo} → PhaseReviewItem#{match.Id}")
                continue

            # 2.2b 无匹配 → 新建 PhaseReviewItem
            max_seq = (
                db.query(PhaseReviewItem.Seq)
                .filter(PhaseReviewItem.PhaseCode == ci.PhaseCode)
                .order_by(PhaseReviewItem.Seq.desc())
                .first()
            )
            max_sort = (
                db.query(PhaseReviewItem.SortOrder)
                .filter(PhaseReviewItem.PhaseCode == ci.PhaseCode)
                .order_by(PhaseReviewItem.SortOrder.desc())
                .first()
            )
            pri = PhaseReviewItem(
                PhaseCode=ci.PhaseCode,
                CheckItemId=ci.Id,
                Seq=(max_seq[0] + 1) if max_seq else 1,
                SortOrder=(max_sort[0] + 1) if max_sort else 1,
                ItemName=ci.Name,
                Request=(ci.Request or "")[:200] or None,
            )
            db.add(pri)
            created += 1
            print(f"[migrate] 新建: {ci.PhaseCode} / {ci.ItemNo} / {ci.Name}")

        db.commit()
        print(f"[migrate] 同步完成: 关联 {linked} 条, 新建 {created} 条, 跳过 {skipped} 条")
    finally:
        db.close()


def main() -> None:
    print("[migrate] 开始: CheckItem ↔ PhaseReviewItem 联动迁移")
    migrate_schema()
    sync_data()
    print("[migrate] 全部完成")


if __name__ == "__main__":
    main()
