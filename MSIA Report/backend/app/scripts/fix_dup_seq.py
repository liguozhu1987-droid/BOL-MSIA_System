"""一次性修正: 迁移新建条目的 Seq 冲突

迁移脚本同批次新建多条时, max(Seq) 查询看不到未 flush 的记录,
导致 MSIA1 #109/#110 都是 Seq=10, MSIA4 #112/#113 都是 Seq=15。
按 Id 顺序将冲突条目重编为连续值。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.phase_review_item import PhaseReviewItem  # noqa: E402

# 需要重排的 (阶段, 起始 Seq, [按顺序的 Id 列表])
FIXES = [
    ("MSIA1", 10, [109, 110]),
    ("MSIA4", 15, [112, 113]),
]


def main() -> None:
    db = SessionLocal()
    try:
        for phase, start_seq, ids in FIXES:
            for offset, pid in enumerate(ids):
                pri = db.query(PhaseReviewItem).filter(PhaseReviewItem.Id == pid).first()
                if not pri or pri.IsDeleted:
                    print(f"[fix] #{pid} 不存在或已删除, 跳过")
                    continue
                new_seq = start_seq + offset
                print(f"[fix] {phase} #{pid}: Seq {pri.Seq} -> {new_seq}")
                pri.Seq = new_seq
                pri.SortOrder = new_seq
        db.commit()
        print("[fix] 完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
