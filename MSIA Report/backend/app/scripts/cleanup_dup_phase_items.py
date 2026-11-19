"""一次性清理: 软删与审核标准联动条目语义重复的 Excel 原始 PhaseReviewItem

重复对 (保留联动新条目, 软删 Excel 原始条目):
  MSIA1 #63 Process CC/SC list                      vs CheckItemId=11 条目
  MSIA2 #72 Process CC/SC list                      vs CheckItemId=18 条目
  MSIA4 #94 Maintenance documents                   vs CheckItemId=40 条目
  MSIA4 #95 Work instructions                       vs CheckItemId=41 条目
  MSIA5 #103 Cpk/Cmk/GR&R validation plan           vs CheckItemId=49 条目

若旧条目已有关联评审记录则跳过 (不删)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.phase_review_item import PhaseReviewItem  # noqa: E402
from app.models.review import ReviewRecord  # noqa: E402

DUP_IDS = [63, 72, 94, 95, 103]


def main() -> None:
    db = SessionLocal()
    try:
        for pid in DUP_IDS:
            pri = db.query(PhaseReviewItem).filter(PhaseReviewItem.Id == pid).first()
            if not pri:
                print(f"[cleanup] #{pid} 不存在, 跳过")
                continue
            review_count = (
                db.query(ReviewRecord)
                .filter(ReviewRecord.PhaseReviewItemId == pid)
                .count()
            )
            if review_count > 0:
                print(f"[cleanup] #{pri.Id} {pri.ItemName!r} 有 {review_count} 条评审记录, 跳过")
                continue
            pri.IsDeleted = True
            print(f"[cleanup] 已软删 #{pri.Id} {pri.ItemName!r} ({pri.PhaseCode})")
        db.commit()
        print("[cleanup] 完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
