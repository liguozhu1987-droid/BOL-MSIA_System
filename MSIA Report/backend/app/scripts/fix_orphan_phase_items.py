"""一次性修复: 软删孤儿 PhaseReviewItem (其 CheckItemId 指向已删除/不存在的审核标准)

运行方式:
    cd backend
    C:\\python\\python.exe -X utf8 -m app.scripts.fix_orphan_phase_items
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.check_item import CheckItem  # noqa: E402
from app.models.phase_review_item import PhaseReviewItem  # noqa: E402


def main() -> None:
    db = SessionLocal()
    fixed = 0
    try:
        active_pris = db.query(PhaseReviewItem).filter(
            PhaseReviewItem.IsDeleted == False,  # noqa: E712
            PhaseReviewItem.CheckItemId.isnot(None),
        ).all()
        for p in active_pris:
            ci = db.query(CheckItem).filter(CheckItem.Id == p.CheckItemId).first()
            if ci is None or ci.IsDeleted:
                state = "CheckItem不存在" if ci is None else "CheckItem已软删"
                p.IsDeleted = True
                fixed += 1
                print(f"[fix] 软删 PhaseReviewItem#{p.Id} {p.ItemName!r} ({p.PhaseCode}) -> {state}")
        db.commit()
        print(f"[fix] 完成: 共修复 {fixed} 条孤儿数据")
    finally:
        db.close()


if __name__ == "__main__":
    main()
