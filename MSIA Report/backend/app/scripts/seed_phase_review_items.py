"""MSIA 阶段评审检查项种子数据脚本

直接从 00. MSIA Check list_template.xlsx 的 Report MSIA1~5 sheet 读取,
按各阶段实际评审清单导入 (Doc./Action 类型, Request 要求).

与 seed_check_items.py (Evaluation Standards 7 档评分标准库) 分离, 互不干扰.

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.seed_phase_review_items

Excel 结构 (Report MSIA1~5 sheet, 从 Row 17 开始):
    B: MSIA (阶段标签, 仅首行)
    C: Doc. / Action (类型标记, 出现在某项前表示后续项的类型)
    D: Item (检查项名称)
    E: Request (要求, 如 Reviewed / Countersigned / Aligned)
    F: Result (评审结果, 评审员填写)
    G: Comments (评审意见, 评审员填写)

注意: Row 17 是表头, Row 18 通常为空, 数据从 Row 19 开始.
最后几行是 Reviewers / Review place, 跳过.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, create_tables  # noqa: E402
from app.models.phase_review_item import PhaseReviewItem  # noqa: E402


# Excel 文件路径
PROJECT_ROOT = ROOT.parent.parent
EXCEL_FILE = PROJECT_ROOT / "00. MSIA Check list_template.xlsx"

# Report MSIA1~5 sheet 名称
REPORT_SHEETS = ["Report MSIA1", "Report MSIA2", "Report MSIA3", "Report MSIA4", "Report MSIA5"]

# Excel 列索引 (1-based)
COL_MSIA = 2      # B
COL_TYPE = 3      # C (Doc. / Action)
COL_ITEM = 4      # D
COL_REQUEST = 5   # E

# 数据开始行 (Row 17 是表头, Row 19 开始为数据)
DATA_START_ROW = 19


def _clean_cell(val) -> str:
    """清理单元格值"""
    if val is None:
        return ""
    s = str(val).strip()
    return s


def _is_skip_row(c_cell: str, d_cell: str) -> bool:
    """判断是否跳过该行 (Reviewers/Review place/空行)"""
    if not d_cell and not c_cell:
        return True
    if c_cell.lower() in ("reviewers:", "review place:"):
        return True
    # 跳过评审员姓名行 (D 列空, C 列为姓名)
    if not d_cell and c_cell:
        return True
    return False


def parse_sheet(sheet) -> List[dict]:
    """解析单个 Report MSIA sheet, 返回检查项数据列表"""
    items: List[dict] = []
    current_phase: Optional[str] = None
    current_item_type: str = "Doc."  # 默认类型

    for row_idx in range(DATA_START_ROW, sheet.max_row + 1):
        b_cell = _clean_cell(sheet.cell(row=row_idx, column=COL_MSIA).value)
        c_cell = _clean_cell(sheet.cell(row=row_idx, column=COL_TYPE).value)
        d_cell = _clean_cell(sheet.cell(row=row_idx, column=COL_ITEM).value)
        e_cell = _clean_cell(sheet.cell(row=row_idx, column=COL_REQUEST).value)

        # 检测阶段切换
        if b_cell.upper().startswith("MSIA"):
            current_phase = b_cell.upper()

        # 跳过空行和评审员信息行
        if _is_skip_row(c_cell, d_cell):
            continue

        # 类型切换: 如果 C 列有值 (Doc. / Action), 更新当前类型
        if c_cell in ("Doc.", "Action"):
            current_item_type = c_cell
        elif c_cell and c_cell not in ("Doc.", "Action"):
            # C 列为其他内容, 跳过
            continue

        # 数据行
        items.append({
            "phase_code": current_phase or "MSIA1",
            "item_type": current_item_type,
            "item_name": d_cell,
            "request": e_cell,
        })

    return items


def parse_excel() -> List[dict]:
    """解析所有 Report MSIA sheet"""
    try:
        import openpyxl
    except ImportError:
        print("[seed-phase] 错误: 需要安装 openpyxl")
        sys.exit(1)

    if not EXCEL_FILE.exists():
        print(f"[seed-phase] 错误: Excel 文件不存在: {EXCEL_FILE}")
        sys.exit(1)

    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    all_items: List[dict] = []

    for sheet_name in REPORT_SHEETS:
        if sheet_name not in wb.sheetnames:
            print(f"[seed-phase] 警告: sheet 不存在 {sheet_name}, 跳过")
            continue
        ws = wb[sheet_name]
        items = parse_sheet(ws)
        all_items.extend(items)
        print(f"[seed-phase] {sheet_name}: 解析 {len(items)} 项")

    return all_items


def seed_phase_review_items() -> None:
    """执行种子数据导入 (upsert)"""
    print(f"[seed-phase] 读取 Excel: {EXCEL_FILE}")
    items_data = parse_excel()
    print(f"[seed-phase] 共解析 {len(items_data)} 项检查项")

    if not items_data:
        print("[seed-phase] 警告: 未解析到任何数据, 终止")
        return

    # 确保表已创建
    create_tables()
    print("[seed-phase] 表已确认创建")

    db = SessionLocal()
    try:
        # 查询现有数据, 按 (PhaseCode, ItemName) 建索引
        existing = db.query(PhaseReviewItem).filter(PhaseReviewItem.IsDeleted == False).all()  # noqa: E712
        existing_map = {(it.PhaseCode, it.ItemName): it for it in existing}

        # 软删除所有旧数据 (重新构建, 保证顺序和内容与 Excel 一致)
        for item in existing:
            item.IsDeleted = True
        db.flush()
        print(f"[seed-phase] 软删除旧数据 {len(existing)} 条")

        # 插入新数据
        inserted = 0
        for idx, item_data in enumerate(items_data):
            # 每个阶段内重新计数序号
            phase_items = [it for it in items_data if it["phase_code"] == item_data["phase_code"]]
            seq = phase_items.index(item_data) + 1

            item = PhaseReviewItem(
                PhaseCode=item_data["phase_code"],
                Seq=seq,
                ItemType=item_data["item_type"],
                ItemName=item_data["item_name"],
                Request=item_data["request"],
                SortOrder=idx,
                IsDeleted=False,
            )
            db.add(item)
            inserted += 1

        db.commit()
        print(f"[seed-phase] 成功: 新增 {inserted} 条")

        # 按阶段统计
        from collections import Counter
        phase_counter = Counter(d["phase_code"] for d in items_data)
        for phase, count in sorted(phase_counter.items()):
            doc_count = sum(1 for d in items_data if d["phase_code"] == phase and d["item_type"] == "Doc.")
            action_count = sum(1 for d in items_data if d["phase_code"] == phase and d["item_type"] == "Action")
            req_count = sum(1 for d in items_data if d["phase_code"] == phase and d["request"])
            print(f"  {phase}: {count} 项 (Doc. {doc_count}, Action {action_count}, 有要求 {req_count})")

        # 打印示例
        print("\n[seed-phase] 示例 (MSIA1):")
        msia1_items = [d for d in items_data if d["phase_code"] == "MSIA1"]
        for d in msia1_items[:5]:
            req = d["request"] or "(空)"
            print(f"  [{d['item_type']}] {d['item_name']}  →  {req}")

    except Exception as exc:
        db.rollback()
        print(f"[seed-phase] 失败: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_phase_review_items()
