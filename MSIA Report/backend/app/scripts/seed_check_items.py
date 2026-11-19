"""MSIA 检查项标准库种子数据脚本

直接从 00. MSIA Check list_template.xlsx 的 Evaluation Standards sheet 读取数据,
按 7 档 Maturity 评分体系 (0% / 25% / 33% / 50% / 67% / 75% / 100%) 导入。

运行方式:
    cd backend
    C:\\python\\python.exe -m app.scripts.seed_check_items

数据来源:
    文件: 00. MSIA Check list_template.xlsx
    Sheet: Evaluation Standards
    版本: ICH-QT-QP-008-01F

Excel 列映射:
    A: Review Type (MSIA1~MSIA5, 阶段标题行)
    B: No. (1.1, 2.0, ...)
    C: Check item
    D: Key item (x 标记)
    E~K: Maturity 7 档评分描述 (0, 0.25, 0.33, 0.5, 0.67, 0.75, 1)
    O: Reviewers
    P: Evidences
    Q: References/Standards
    R: Remarks
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional

# 让脚本既可在包内导入也可直接运行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.check_item import CheckItem  # noqa: E402


# ============ Excel 文件路径 ============
# ROOT = backend/app (因为 __file__ = backend/app/scripts/seed_check_items.py)
# 项目根 = ROOT.parent.parent = backend 的上一级
PROJECT_ROOT = ROOT.parent.parent
EXCEL_FILE = PROJECT_ROOT / "00. MSIA Check list_template.xlsx"

# 7 档 Maturity 评分定义
MATURITY_LEVELS = [
    {"score": 0.0, "label": "0%", "col": "E"},     # col index 5
    {"score": 0.25, "label": "25%", "col": "F"},   # col index 6
    {"score": 0.33, "label": "33%", "col": "G"},   # col index 7
    {"score": 0.5, "label": "50%", "col": "H"},    # col index 8
    {"score": 0.67, "label": "67%", "col": "I"},   # col index 9
    {"score": 0.75, "label": "75%", "col": "J"},   # col index 10
    {"score": 1.0, "label": "100%", "col": "K"},   # col index 11
]

# Excel 列索引 (1-based)
COL_REVIEW_TYPE = 1    # A
COL_ITEM_NO = 2        # B
COL_NAME = 3           # C
COL_KEY_ITEM = 4       # D
COL_MATURITY_START = 5  # E (0%)
COL_MATURITY_END = 11   # K (100%)
COL_REVIEWERS = 15     # O
COL_EVIDENCES = 16     # P
COL_REFERENCES = 17    # Q
COL_REMARKS = 18       # R

# 匹配阶段代码 (如 MSIA1, MSIA2, ...)
PHASE_PATTERN = re.compile(r"^(MSIA\d)\b", re.MULTILINE)


def _clean_cell(val) -> str:
    """清理单元格值: 去除首尾空白, 合并多余换行"""
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    # 合并连续空格 (保留换行)
    s = re.sub(r"[^\S\n]+", " ", s)
    # 合并连续换行
    s = re.sub(r"\n{2,}", "\n", s)
    return s


def _extract_phase_code(review_type_val: str) -> Optional[str]:
    """从 Review Type 列提取阶段代码 (MSIA1~MSIA5)"""
    if not review_type_val:
        return None
    m = PHASE_PATTERN.search(review_type_val)
    return m.group(1) if m else None


def _build_score_options(maturity_descs: List[str]) -> str:
    """构建 7 档评分选项 JSON"""
    options = []
    for level, desc in zip(MATURITY_LEVELS, maturity_descs):
        options.append({
            "score": level["score"],
            "label": level["label"],
            "desc": desc or "",  # 空单元格保留为空字符串
        })
    return json.dumps(options, ensure_ascii=False)


def parse_excel() -> List[dict]:
    """解析 Excel 文件, 返回检查项数据列表"""
    try:
        import openpyxl
    except ImportError:
        print("[seed] 错误: 需要安装 openpyxl (pip install openpyxl)")
        sys.exit(1)

    if not EXCEL_FILE.exists():
        print(f"[seed] 错误: Excel 文件不存在: {EXCEL_FILE}")
        sys.exit(1)

    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    ws = wb["Evaluation Standards"]

    items: List[dict] = []
    current_phase: Optional[str] = None
    skipped_header_rows = 0

    for row_idx in range(1, ws.max_row + 1):
        # 读取各列
        review_type = _clean_cell(ws.cell(row=row_idx, column=COL_REVIEW_TYPE).value)
        item_no = _clean_cell(ws.cell(row=row_idx, column=COL_ITEM_NO).value)
        name = _clean_cell(ws.cell(row=row_idx, column=COL_NAME).value)
        key_item = _clean_cell(ws.cell(row=row_idx, column=COL_KEY_ITEM).value)
        reviewers = _clean_cell(ws.cell(row=row_idx, column=COL_REVIEWERS).value)
        evidences = _clean_cell(ws.cell(row=row_idx, column=COL_EVIDENCES).value)
        references = _clean_cell(ws.cell(row=row_idx, column=COL_REFERENCES).value)
        remarks = _clean_cell(ws.cell(row=row_idx, column=COL_REMARKS).value)

        # 检测阶段切换
        phase_in_row = _extract_phase_code(review_type)
        if phase_in_row:
            current_phase = phase_in_row
            # 阶段标题行通常没有 item_no, 跳过
            if not item_no:
                continue

        # 跳过空行或表头
        if not item_no or not name:
            # 跳过没有编号的行 (可能是空行或注释)
            if not review_type and not item_no and not name:
                continue
            skipped_header_rows += 1
            continue

        # 跳过表头行 (No. 等文字)
        if item_no.lower() == "no." or item_no == "No.":
            continue

        # 读取 7 档 Maturity 描述
        maturity_descs = []
        for col_idx in range(COL_MATURITY_START, COL_MATURITY_END + 1):
            desc = _clean_cell(ws.cell(row=row_idx, column=col_idx).value)
            maturity_descs.append(desc)

        # 构建评分选项 JSON
        score_options = _build_score_options(maturity_descs)

        # 确定阶段代码
        phase_code = current_phase or "MSIA1"

        # IsKeyItem: 列 D 为 "x" 时为关键项
        is_key_item = key_item.lower() == "x"

        # 组装证据到备注
        remarks_text = remarks
        if evidences:
            if remarks_text:
                remarks_text = f"{remarks_text}\nEvidence: {evidences}"
            else:
                remarks_text = f"Evidence: {evidences}"

        items.append({
            "phase_code": phase_code,
            "item_no": item_no,
            "name": name,
            "is_key_item": is_key_item,
            "reviewer_roles": reviewers,
            "reference_documents": references,
            "remarks": remarks_text,
            "evidence": evidences,
            "score_scale_type": "7-step",
            "score_options": score_options,
        })

    return items


def seed_check_items() -> None:
    """执行种子数据导入 (upsert: 存在则更新, 不存在则插入)

    为避免外键约束冲突 (Issue.ItemId -> CheckItem.Id),
    不再硬删除旧数据, 改为按 (PhaseCode, ItemNo) 唯一键 upsert.
    对脚本未覆盖的旧 MSIA 检查项, 软删除 (IsDeleted=True).
    """
    print(f"[seed] 读取 Excel: {EXCEL_FILE}")
    check_items_data = parse_excel()
    print(f"[seed] 解析得到 {len(check_items_data)} 项检查项")

    if not check_items_data:
        print("[seed] 警告: 未解析到任何数据, 终止")
        return

    db = SessionLocal()
    try:
        # 1. 查询现有 MSIA 检查项, 按 (PhaseCode, ItemNo) 建索引
        existing_items = (
            db.query(CheckItem)
            .filter(CheckItem.PhaseCode.like("MSIA%"))
            .all()
        )
        existing_map = {(it.PhaseCode, it.ItemNo): it for it in existing_items}
        existing_keys = set(existing_map.keys())

        # 2. 本脚本将覆盖的 (PhaseCode, ItemNo) 集合
        new_keys = {(d["phase_code"], d["item_no"]) for d in check_items_data}

        # 3. 软删除: 旧 MSIA 检查项不在新数据中的, 标记 IsDeleted=True
        soft_deleted = 0
        for key, item in existing_map.items():
            if key not in new_keys and not item.IsDeleted:
                item.IsDeleted = True
                soft_deleted += 1
        if soft_deleted:
            print(f"[seed] 软删除旧检查项 {soft_deleted} 条 (不在新版标准库中)")

        # 4. upsert: 存在则更新, 不存在则插入
        inserted = 0
        updated = 0
        for item_data in check_items_data:
            key = (item_data["phase_code"], item_data["item_no"])
            existing = existing_map.get(key)
            if existing:
                # 更新现有记录
                existing.Name = item_data["name"]
                existing.Request = ""  # Request 列废弃, 改用 ScoreOptions 存储 7 档评分
                existing.RequestDescription = ""
                existing.IsKeyItem = item_data["is_key_item"]
                existing.ReviewerRoles = item_data["reviewer_roles"]
                existing.ReferenceDocuments = item_data["reference_documents"]
                existing.ScoreScaleType = item_data["score_scale_type"]
                existing.ScoreOptions = item_data["score_options"]
                existing.DefaultResultText = ""
                existing.Remarks = item_data["remarks"]
                existing.IsDeleted = False
                existing.Version = (existing.Version or 1) + 1
                updated += 1
            else:
                # 插入新记录
                item = CheckItem(
                    PhaseCode=item_data["phase_code"],
                    ItemNo=item_data["item_no"],
                    Name=item_data["name"],
                    Request="",
                    RequestDescription="",
                    IsKeyItem=item_data["is_key_item"],
                    ReviewerRoles=item_data["reviewer_roles"],
                    ReferenceDocuments=item_data["reference_documents"],
                    ScoreScaleType=item_data["score_scale_type"],
                    ScoreOptions=item_data["score_options"],
                    DefaultResultText="",
                    Version=1,
                    Remarks=item_data["remarks"],
                    IsDeleted=False,
                )
                db.add(item)
                inserted += 1

        db.commit()
        print(f"[seed] 成功: 新增 {inserted} 条, 更新 {updated} 条")

        # 按阶段统计
        from collections import Counter
        phase_counter = Counter(d["phase_code"] for d in check_items_data)
        for phase, count in sorted(phase_counter.items()):
            key_count = sum(
                1
                for d in check_items_data
                if d["phase_code"] == phase and d["is_key_item"]
            )
            print(f"  {phase}: {count} 项 (其中关键项 {key_count})")

        # 打印示例 (第一项的评分矩阵)
        if check_items_data:
            sample = check_items_data[0]
            print(f"\n[seed] 示例 - {sample['phase_code']} {sample['item_no']} {sample['name']}:")
            opts = json.loads(sample["score_options"])
            for opt in opts:
                desc_preview = (opt["desc"][:60] + "...") if len(opt["desc"]) > 60 else opt["desc"]
                empty_tag = " (空)" if not opt["desc"] else ""
                print(f"  {opt['label']:>5}: {desc_preview}{empty_tag}")

    except Exception as exc:
        db.rollback()
        print(f"[seed] 失败: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_check_items()
