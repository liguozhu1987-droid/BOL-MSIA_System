# -*- coding: utf-8 -*-
"""预算BOL Excel 模板生成器

支持两种标准模板（与官方 Excel "2026 Achievable BOL Summary.xlsx" 中的 sheet 结构一致）：
- budget    模板对应 sheet "2026 Budget BOL"：仅录入目标 BOL 数值
- achievable 模板对应 sheet "2026 Achievable BOL"：录入 CT/HC 由系统计算 BOL

两种模板都保留 Process Type / Project Code / Asset / Plant 基本列，
项目其他信息（客户、SOP/EOP、产品类型、Roof Type 等）由后端在导入时
通过 CMC cbco_records 表的 program_number 自动同步，无需用户在 Excel 中填写。
"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


# ============================================================
# 模板类型常量
# ============================================================
TYPE_BUDGET = 'budget'
TYPE_ACHIEVABLE = 'achievable'
TYPE_TARGET = 'target'
TYPE_ORIGINAL = 'original'  # 兼容旧版 Original data 模板
VALID_TYPES = {TYPE_BUDGET, TYPE_ACHIEVABLE, TYPE_TARGET, TYPE_ORIGINAL}

# 模板显示名
TYPE_LABELS = {
    TYPE_BUDGET: 'Budget BOL 上传模板',
    TYPE_ACHIEVABLE: 'Achievable BOL 上传模板',
    TYPE_TARGET: 'Target BOL 上传模板',
    TYPE_ORIGINAL: 'Original data 上传模板（旧版兼容）',
}


# ============================================================
# Budget BOL 模板表头（对应 sheet "2026 Budget BOL"）
# 用户只需填写 Process Type / Project Code / Asset / Plant / 三个 BOL 数值列
# ============================================================
BUDGET_TEMPLATE_HEADERS = [
    'Process Type',          # 第1列 工艺类型（FA/IHR/OB/FR/LiG/bonding 等）
    'Project Code',          # 第2列 项目代码（必填，用于关联 cbco_records）
    'Asset',                 # 第3列 产线编号
    'Plant',                 # 第4列 工厂（Beijing/Shanghai/Guangzhou/Chongqing/Changchun/Wuhan）
    'AME Target BOL',        # 第5列 AME 目标 BOL（参考值，可空）
    'Achievable BOL',        # 第6列 可达 BOL（参考值，可空）
    'Budget BOL',            # 第7列 预算 BOL（必填，作为最终入库的 BOL 值）
]
BUDGET_COLUMN_WIDTHS = [16, 16, 14, 16, 16, 16, 16]


# ============================================================
# Achievable BOL 模板表头（对应 sheet "2026 Achievable BOL"）
# 用户填写 CT/HC，BOL 由系统按公式 CT×HC×(1+1/15)/OEE/60 计算
# ============================================================
ACHIEVABLE_TEMPLATE_HEADERS = [
    'Process Type',              # 第1列 工艺类型
    'Project Code',              # 第2列 项目代码（必填）
    'Asset',                     # 第3列 产线编号
    'Plant',                     # 第4列 工厂
    'Process1_ct_second',        # 第5列 子工艺1 CT（秒）
    'Process1_HC_per_shift',     # 第6列 子工艺1 HC（人/班）
    'Comment1',                  # 第7列 子工艺1 备注
    'Process2_ct_second',        # 第8列 子工艺2 CT
    'Process2_HC_per_shift',     # 第9列 子工艺2 HC
    'Comment2',                  # 第10列 子工艺2 备注
    'Process3_ct_second',        # 第11列 子工艺3 CT
    'Process3_HC_per_shift',     # 第12列 子工艺3 HC
    'Comment3',                  # 第13列 子工艺3 备注
    'Process4_ct_second',        # 第14列 子工艺4 CT
    'Process4_HC_per_shift',     # 第15列 子工艺4 HC
    'Comment4',                  # 第16列 子工艺4 备注
    'Process5_ct_second',        # 第17列 子工艺5 CT
    'Process5_HC_per_shift',     # 第18列 子工艺5 HC
    'Comment5',                  # 第19列 子工艺5 备注
    'OEE Actual',                # 第20列 OEE（0~1，默认0.85）
    'BOL Base',                  # 第21列 BOL 基准（只读/参考）
    'Uplift Indirect Hours',     # 第22列 间接工时系数（默认0.0667）
    'BOL(mins)',                 # 第23列 计算后的 BOL（分钟）
]
ACHIEVABLE_COLUMN_WIDTHS = [
    16, 16, 14, 16,
    14, 14, 16, 14, 14, 16, 14, 14, 16, 14, 14, 16, 14, 14, 16,
    12, 12, 14, 12,
]


# ============================================================
# Target BOL 模板表头（对应 sheet "2026 Target BOL"）
# 与 Achievable 模板差异：Target sheet 的 OEE 在第22列（Achievable 在第20列），
# 计算列 BOL\nBase / Uplift Indirect Hours / OEE / BOL\n (minutes) 在第20-23列。
# ============================================================
TARGET_TEMPLATE_HEADERS = [
    'Process Type',        # 第1列 工艺类型（与 Achievable 模板一致：FA/IHR/OB/FR/LiG/bonding 等）
    'Project\n Code',                  # 第2列 项目代码（必填）
    'Asset',                            # 第3列 产线编号
    'Plant',                            # 第4列 工厂
    'Tact-time bottle-neck station (in seconds)',  # 第5列 主工艺 CT
    'Number of Operators per Shift',    # 第6列 主工艺 HC
    'Comment',                          # 第7列 主工艺备注
    'CT #2', 'HC #2', 'Comment #2',     # 第8~10列 子工艺2
    'CT #3', 'HC #3', 'Comment #3',     # 第11~13列 子工艺3
    'CT #4', 'HC #4', 'Comment #4',     # 第14~16列 子工艺4
    'CT #5', 'HC #5', 'Comment #5',     # 第17~19列 子工艺5
    'BOL\nBase',                        # 第20列 BOL 基准（只读）
    'Uplift Indirect Hours',            # 第21列 间接工时系数
    'OEE',                              # 第22列 OEE
    'BOL\n (minutes)',                  # 第23列 BOL（分钟）
]
TARGET_COLUMN_WIDTHS = [
    20, 14, 14, 16,
    18, 14, 16, 10, 8, 16, 10, 8, 16, 10, 8, 16, 10, 8, 16,
    12, 14, 12, 14,
]


# ============================================================
# Original data 模板表头（旧版兼容，对应 "Original data" sheet）
# ============================================================
ORIGINAL_TEMPLATE_HEADERS = [
    'Category for capacity planning',           # 第1列 工艺类别
    'Project Code',                              # 第2列 项目代码
    'Asset',                                     # 第3列 产线编号
    'Plant',                                     # 第4列 工厂
    'Customer',                                  # 第5列 客户
    'Programs',                                  # 第6列 项目名称
    'Roof type',                                 # 第7列 顶棚类型
    'Status',                                    # 第8列 状态
    'SOP',                                       # 第9列 SOP 日期
    'EOP',                                       # 第10列 EOP 日期
    'Tact-time bottle-neck station (in seconds)',  # 第11列 主工艺 CT
    'Number of Operators per Shift',             # 第12列 主工艺 HC
    'Comment',                                   # 第13列 主工艺备注
    'CT #2', 'HC #2', 'Comment #2',              # 第14~16列 子工艺2
    'CT #3', 'HC #3', 'Comment #3',              # 第17~19列 子工艺3
    'CT #4', 'HC #4', 'Comment #4',              # 第20~22列 子工艺4
    'CT #5', 'HC #5', 'Comment #5',              # 第23~25列 子工艺5
]
ORIGINAL_COLUMN_WIDTHS = [
    18, 14, 12, 14, 14, 36, 18, 10, 12, 12,
    18, 14, 16, 10, 8, 16, 10, 8, 16, 10, 8, 16, 10, 8, 16,
]


# ============================================================
# 生成函数
# ============================================================
def _style_header_row(ws, headers, fill_color='2563EB'):
    """统一表头样式：深蓝底白字、居中、自动换行、冻结首行"""
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color=fill_color, end_color=fill_color,
                              fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center',
                             wrap_text=True)
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
    ws.row_dimensions[1].height = 36
    ws.freeze_panes = 'A2'


def _set_column_widths(ws, widths):
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def _add_instruction_row(ws, instruction_text, n_cols):
    """在表头下方插入一行黄色说明，提示用户填写规则"""
    ws.cell(row=2, column=1, value=instruction_text)
    ws.cell(row=2, column=1).font = Font(italic=True, color='B45309', size=10)
    ws.cell(row=2, column=1).fill = PatternFill(
        start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
    ws.cell(row=2, column=1).alignment = Alignment(
        horizontal='left', vertical='center', wrap_text=True)
    # 合并第2行的所有列
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_cols)
    ws.row_dimensions[2].height = 30
    # 数据从第3行开始（冻结改为 A3）
    ws.freeze_panes = 'A3'


def generate_budget_template():
    """生成 Budget BOL 模板工作簿（用户填写目标 BOL 数值）"""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Budget BOL'
    _style_header_row(ws, BUDGET_TEMPLATE_HEADERS, fill_color='2563EB')
    _set_column_widths(ws, BUDGET_COLUMN_WIDTHS)
    _add_instruction_row(
        ws,
        '说明：填写 Project Code（必填）、Process Type、Asset、Plant；'
        'Budget BOL 列为最终入库的 BOL 值（必填）；'
        'AME Target BOL / Achievable BOL 为参考值，可空。'
        '客户/SOP/EOP/产品类型/Roof Type 等由系统自动从 cbco_records 同步。',
        len(BUDGET_TEMPLATE_HEADERS),
    )
    return wb


def generate_achievable_template():
    """生成 Achievable BOL 模板工作簿（用户填写 CT/HC，BOL 由系统计算）"""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Achievable BOL'
    _style_header_row(ws, ACHIEVABLE_TEMPLATE_HEADERS, fill_color='0891B2')
    _set_column_widths(ws, ACHIEVABLE_COLUMN_WIDTHS)
    _add_instruction_row(
        ws,
        '说明：填写 Project Code（必填）、Process Type、Asset、Plant；'
        'Process1_ct_second / Process1_HC_per_shift 为子工艺1的 CT/HC（必填）；'
        '子工艺2~5 的 CT/HC 可选；OEE Actual 默认 0.85；'
        'BOL Base / Uplift Indirect Hours / BOL(mins) 为系统自动计算，无需填写。'
        '客户/SOP/EOP/产品类型/Roof Type 等由系统自动从 cbco_records 同步。',
        len(ACHIEVABLE_TEMPLATE_HEADERS),
    )
    return wb


def generate_target_template():
    """生成 Target BOL 模板工作簿（对应 sheet "2026 Target BOL"）

    与 Achievable 的差异：
    - 第1列：Category for capacity planning（容量规划分类，如 FA）
    - 第22列：OEE（Achievable 在第20列）
    - BOL 字段在第23列
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Target BOL'
    _style_header_row(ws, TARGET_TEMPLATE_HEADERS, fill_color='7C3AED')
    _set_column_widths(ws, TARGET_COLUMN_WIDTHS)
    _add_instruction_row(
        ws,
        '说明：填写 Project\n Code（必填）、Process Type、Asset、Plant；'
        '主工艺 CT/HC（第5-6列）必填，子工艺 CT#2~#5 可选；'
        'OEE 默认为 0.85；BOL\nBase / Uplift Indirect Hours / BOL\n (minutes) 为系统自动计算。'
        '客户/SOP/EOP/产品类型/Roof Type 等由系统自动从 cbco_records 同步。',
        len(TARGET_TEMPLATE_HEADERS),
    )
    return wb


def generate_original_template():
    """生成 Original data 模板（旧版兼容，结构与原 'Original data' sheet 一致）"""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Original data'
    _style_header_row(ws, ORIGINAL_TEMPLATE_HEADERS, fill_color='4472C4')
    _set_column_widths(ws, ORIGINAL_COLUMN_WIDTHS)
    return wb


def generate_template(template_type=TYPE_ACHIEVABLE):
    """生成指定类型的模板工作簿

    Args:
        template_type: 'budget' | 'achievable' | 'target' | 'original'

    Returns:
        openpyxl.Workbook
    """
    if template_type == TYPE_BUDGET:
        return generate_budget_template()
    if template_type == TYPE_ACHIEVABLE:
        return generate_achievable_template()
    if template_type == TYPE_TARGET:
        return generate_target_template()
    if template_type == TYPE_ORIGINAL:
        return generate_original_template()
    # 默认 achievable
    return generate_achievable_template()


def generate_template_bytes(template_type=TYPE_ACHIEVABLE):
    """生成模板的 .xlsx 字节流，便于通过 HttpResponse 直接下载"""
    wb = generate_template(template_type)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
