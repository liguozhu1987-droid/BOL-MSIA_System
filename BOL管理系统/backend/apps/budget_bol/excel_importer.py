# -*- coding: utf-8 -*-
"""预算BOL Excel 导入器（重构版）

按用户要求重构为纯导入逻辑：
1. 不再与任何表关联查询，仅将 Excel 内容直接导入数据库
2. Plant 列原值直接存储为 plant 字段，不再做 _map_location 映射
3. Process Type 列只存 Excel 第1列原值（FA/IHR/IHE 等），不再拆分子工艺
4. 每行 Excel = 一条数据库记录，子工艺数据通过 process1~5 字段存储

三种 BOL 类型导入目标：
- BUDGET     → BudgetBol 表（7列结构）
- ACHIEVABLE → AchievableTargetBol 表（23列结构，OEE 在第20列）
- TARGET     → AchievableTargetBol 表（23列结构，OEE 在第22列）

导入流程（全量替换）：
1. 先清空该财年该类型的所有旧记录
2. 再全量导入 Excel 中的新数据
3. 整个操作在事务中执行，任一环节失败则回滚
"""
from decimal import Decimal

from django.db import transaction
from openpyxl import load_workbook

from apps.budget_bol.models import BudgetBol, AchievableTargetBol


# ============================================================
# BOL 类型常量
# ============================================================
TYPE_BUDGET = 'BUDGET'
TYPE_ACHIEVABLE = 'ACHIEVABLE'
TYPE_TARGET = 'TARGET'
VALID_TYPES = {TYPE_BUDGET, TYPE_ACHIEVABLE, TYPE_TARGET}


# ============================================================
# 辅助函数
# ============================================================
def _clean_str(value):
    """清理字符串：去除换行符与首尾空白；None 返回 ''"""
    if value is None:
        return ''
    s = str(value).replace('\n', ' ').replace('\r', ' ').strip()
    return s


def _to_decimal(value):
    """转换为 Decimal；空值或失败返回 None"""
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None


# ============================================================
# 导入器
# ============================================================
class BudgetBolImporter:
    """预算BOL Excel 导入器（重构版）

    用法：
        importer = BudgetBolImporter(
            fiscal_year=2026,
            bol_type='ACHIEVABLE',  # 或 'BUDGET' / 'TARGET'
            created_by='zhangsan',
        )
        result = importer.import_from_file('/path/to/template.xlsx')
    """

    def __init__(self, fiscal_year, bol_type=TYPE_ACHIEVABLE, created_by=''):
        self.fiscal_year = int(fiscal_year)
        self.bol_type = (bol_type or TYPE_ACHIEVABLE).upper()
        if self.bol_type not in VALID_TYPES:
            raise ValueError(f'不支持的 bol_type: {self.bol_type}')
        self.created_by = created_by or ''

    # ------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------
    def import_from_file(self, file_path):
        """从 Excel 文件导入预算BOL，返回统计结果字典

        导入逻辑：先清空该财年该类型的所有旧记录，再全量导入新数据，
        确保数据库与 Excel 完全一致（全量替换而非增量更新）。
        整个操作在事务中执行，任一环节失败则回滚。
        """
        result = {
            'total_rows': 0,
            'imported': 0,
            'skipped': 0,
            'deleted': 0,
            'errors': [],
            'fiscal_year': self.fiscal_year,
            'bol_type': self.bol_type,
        }
        try:
            wb = load_workbook(file_path, data_only=True)
        except Exception as e:
            result['errors'].append(f'打开Excel文件失败: {e}')
            return result

        # 根据 bol_type 选择工作表
        sheet_name = self._pick_sheet(wb.sheetnames)
        if sheet_name and sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb[wb.sheetnames[0]]

        # 数据起始行：第1行为表头，数据从第2行起
        data_start_row = 2

        # 先统计 Excel 中有效数据行数
        valid_rows = 0
        for row_idx in range(data_start_row, ws.max_row + 1):
            project_code = _clean_str(ws.cell(row=row_idx, column=2).value)
            if project_code:
                valid_rows += 1

        if valid_rows == 0:
            result['errors'].append('Excel 中未检测到有效数据行（Project Code 为空），导入已取消')
            return result

        # 在事务中执行：清空旧数据 + 全量导入新数据
        try:
            with transaction.atomic():
                # 步骤1：清空该财年该类型的所有旧记录
                deleted_count = self._clear_old_records()
                result['deleted'] = deleted_count

                # 步骤2：全量导入新数据
                for row_idx in range(data_start_row, ws.max_row + 1):
                    result['total_rows'] += 1
                    try:
                        if self.bol_type == TYPE_BUDGET:
                            self._import_budget_row(ws, row_idx, result)
                        elif self.bol_type == TYPE_TARGET:
                            self._import_target_row(ws, row_idx, result)
                        else:
                            self._import_achievable_row(ws, row_idx, result)
                    except Exception as e:
                        result['errors'].append(f'第{row_idx}行导入失败: {e}')
                        raise  # 事务内抛异常触发回滚

        except Exception as e:
            if not result['errors']:
                result['errors'].append(f'导入事务失败，已回滚: {e}')
            # 清空计数重置（事务回滚后数据恢复）
            result['deleted'] = 0
            result['imported'] = 0

        return result

    def _clear_old_records(self):
        """清空该财年该类型的所有旧记录"""
        if self.bol_type == TYPE_BUDGET:
            qs = BudgetBol.objects.filter(
                fiscal_year=self.fiscal_year,
                bol_type=TYPE_BUDGET,
            )
        else:
            qs = AchievableTargetBol.objects.filter(
                fiscal_year=self.fiscal_year,
                bol_type=self.bol_type,
            )
        deleted_count, _ = qs.delete()
        return deleted_count

    def _pick_sheet(self, sheet_names):
        """根据 bol_type 选择最匹配的 sheet 名"""
        if self.bol_type == TYPE_BUDGET:
            candidates = ['Budget BOL', '2026 Budget BOL', '2025 Budget BOL']
        elif self.bol_type == TYPE_TARGET:
            candidates = ['Target BOL', '2026 Target BOL', '2025 Target BOL']
        else:
            candidates = ['Achievable BOL', '2026 Achievable BOL', '2025 Achievable BOL']
        # 精确匹配
        for name in candidates:
            if name in sheet_names:
                return name
        # 模糊匹配
        for name in sheet_names:
            for c in candidates:
                if c.lower() in name.lower():
                    return name
        return None

    # ------------------------------------------------------------
    # Budget 类型导入（一行 Excel = 一条 BudgetBol 记录，7列）
    # ------------------------------------------------------------
    def _import_budget_row(self, ws, row_idx, result):
        """导入 Budget BOL Excel 行，存入 BudgetBol 表"""
        # Excel 7列结构：
        # 1: Process Type, 2: Project Code, 3: Asset, 4: Plant,
        # 5: AME Target BOL, 6: Achievable BOL, 7: Budget BOL
        project_code = _clean_str(ws.cell(row=row_idx, column=2).value)
        if not project_code:
            result['skipped'] += 1
            return

        process_type = _clean_str(ws.cell(row=row_idx, column=1).value)
        asset = _clean_str(ws.cell(row=row_idx, column=3).value)
        plant = _clean_str(ws.cell(row=row_idx, column=4).value)
        ame_target_bol = _to_decimal(ws.cell(row=row_idx, column=5).value)
        achievable_bol = _to_decimal(ws.cell(row=row_idx, column=6).value)
        budget_bol = _to_decimal(ws.cell(row=row_idx, column=7).value)

        # 直接存储 Plant 原值，不做映射
        BudgetBol.objects.create(
            fiscal_year=self.fiscal_year,
            bol_type=TYPE_BUDGET,
            process_type=process_type[:30],
            project_code=project_code[:30],
            asset=asset[:30],
            plant=plant[:30],
            ame_target_bol=ame_target_bol,
            achievable_bol=achievable_bol,
            budget_bol=budget_bol,
            created_by=self.created_by[:50],
        )
        result['imported'] += 1

    # ------------------------------------------------------------
    # Achievable 类型导入（一行 Excel = 一条记录，23列）
    # 列顺序：1-4 基本信息 / 5-19 子工艺1~5 / 20 OEE / 21 BOL Base / 22 Uplift / 23 BOL
    # ------------------------------------------------------------
    def _import_achievable_row(self, ws, row_idx, result):
        """导入 Achievable BOL Excel 行，存入 AchievableTargetBol 表"""
        project_code = _clean_str(ws.cell(row=row_idx, column=2).value)
        if not project_code:
            result['skipped'] += 1
            return

        process_type = _clean_str(ws.cell(row=row_idx, column=1).value)
        asset = _clean_str(ws.cell(row=row_idx, column=3).value)
        plant = _clean_str(ws.cell(row=row_idx, column=4).value)

        # 子工艺1~5 CT/HC/Comment（第5~19列）
        process1_ct = _to_decimal(ws.cell(row=row_idx, column=5).value)
        process1_hc = _to_decimal(ws.cell(row=row_idx, column=6).value)
        comment1 = _clean_str(ws.cell(row=row_idx, column=7).value)
        process2_ct = _to_decimal(ws.cell(row=row_idx, column=8).value)
        process2_hc = _to_decimal(ws.cell(row=row_idx, column=9).value)
        comment2 = _clean_str(ws.cell(row=row_idx, column=10).value)
        process3_ct = _to_decimal(ws.cell(row=row_idx, column=11).value)
        process3_hc = _to_decimal(ws.cell(row=row_idx, column=12).value)
        comment3 = _clean_str(ws.cell(row=row_idx, column=13).value)
        process4_ct = _to_decimal(ws.cell(row=row_idx, column=14).value)
        process4_hc = _to_decimal(ws.cell(row=row_idx, column=15).value)
        comment4 = _clean_str(ws.cell(row=row_idx, column=16).value)
        process5_ct = _to_decimal(ws.cell(row=row_idx, column=17).value)
        process5_hc = _to_decimal(ws.cell(row=row_idx, column=18).value)
        comment5 = _clean_str(ws.cell(row=row_idx, column=19).value)

        # 第20~23列（Achievable 顺序：OEE/BOL Base/Uplift/BOL）
        oee = _to_decimal(ws.cell(row=row_idx, column=20).value)
        bol_base = _to_decimal(ws.cell(row=row_idx, column=21).value)
        uplift_indirect_hours = _to_decimal(ws.cell(row=row_idx, column=22).value)
        bol = _to_decimal(ws.cell(row=row_idx, column=23).value)

        # 直接存储 Plant 原值
        AchievableTargetBol.objects.create(
            fiscal_year=self.fiscal_year,
            bol_type=TYPE_ACHIEVABLE,
            process_type=process_type[:30],
            project_code=project_code[:30],
            asset=asset[:30],
            plant=plant[:30],
            process1_ct=process1_ct,
            process1_hc=process1_hc,
            comment1=comment1[:200],
            process2_ct=process2_ct,
            process2_hc=process2_hc,
            comment2=comment2[:200],
            process3_ct=process3_ct,
            process3_hc=process3_hc,
            comment3=comment3[:200],
            process4_ct=process4_ct,
            process4_hc=process4_hc,
            comment4=comment4[:200],
            process5_ct=process5_ct,
            process5_hc=process5_hc,
            comment5=comment5[:200],
            oee=oee,
            bol_base=bol_base,
            uplift_indirect_hours=uplift_indirect_hours,
            bol=bol,
            created_by=self.created_by[:50],
        )
        result['imported'] += 1

    # ------------------------------------------------------------
    # Target 类型导入（一行 Excel = 一条记录，23列）
    # 列顺序：1-4 基本信息 / 5-19 子工艺1~5 / 20 BOL Base / 21 Uplift / 22 OEE / 23 BOL
    # ------------------------------------------------------------
    def _import_target_row(self, ws, row_idx, result):
        """导入 Target BOL Excel 行，存入 AchievableTargetBol 表

        与 Achievable 的差异：最后4列顺序不同
        - Achievable: OEE(20) / BOL Base(21) / Uplift(22) / BOL(23)
        - Target:     BOL Base(20) / Uplift(21) / OEE(22) / BOL(23)
        """
        project_code = _clean_str(ws.cell(row=row_idx, column=2).value)
        if not project_code:
            result['skipped'] += 1
            return

        process_type = _clean_str(ws.cell(row=row_idx, column=1).value)
        asset = _clean_str(ws.cell(row=row_idx, column=3).value)
        plant = _clean_str(ws.cell(row=row_idx, column=4).value)

        # 子工艺1~5 CT/HC/Comment（第5~19列，与 Achievable 相同）
        process1_ct = _to_decimal(ws.cell(row=row_idx, column=5).value)
        process1_hc = _to_decimal(ws.cell(row=row_idx, column=6).value)
        comment1 = _clean_str(ws.cell(row=row_idx, column=7).value)
        process2_ct = _to_decimal(ws.cell(row=row_idx, column=8).value)
        process2_hc = _to_decimal(ws.cell(row=row_idx, column=9).value)
        comment2 = _clean_str(ws.cell(row=row_idx, column=10).value)
        process3_ct = _to_decimal(ws.cell(row=row_idx, column=11).value)
        process3_hc = _to_decimal(ws.cell(row=row_idx, column=12).value)
        comment3 = _clean_str(ws.cell(row=row_idx, column=13).value)
        process4_ct = _to_decimal(ws.cell(row=row_idx, column=14).value)
        process4_hc = _to_decimal(ws.cell(row=row_idx, column=15).value)
        comment4 = _clean_str(ws.cell(row=row_idx, column=16).value)
        process5_ct = _to_decimal(ws.cell(row=row_idx, column=17).value)
        process5_hc = _to_decimal(ws.cell(row=row_idx, column=18).value)
        comment5 = _clean_str(ws.cell(row=row_idx, column=19).value)

        # 第20~23列（Target 顺序：BOL Base/Uplift/OEE/BOL）
        bol_base = _to_decimal(ws.cell(row=row_idx, column=20).value)
        uplift_indirect_hours = _to_decimal(ws.cell(row=row_idx, column=21).value)
        oee = _to_decimal(ws.cell(row=row_idx, column=22).value)
        bol = _to_decimal(ws.cell(row=row_idx, column=23).value)

        # 直接存储 Plant 原值
        AchievableTargetBol.objects.create(
            fiscal_year=self.fiscal_year,
            bol_type=TYPE_TARGET,
            process_type=process_type[:30],
            project_code=project_code[:30],
            asset=asset[:30],
            plant=plant[:30],
            process1_ct=process1_ct,
            process1_hc=process1_hc,
            comment1=comment1[:200],
            process2_ct=process2_ct,
            process2_hc=process2_hc,
            comment2=comment2[:200],
            process3_ct=process3_ct,
            process3_hc=process3_hc,
            comment3=comment3[:200],
            process4_ct=process4_ct,
            process4_hc=process4_hc,
            comment4=comment4[:200],
            process5_ct=process5_ct,
            process5_hc=process5_hc,
            comment5=comment5[:200],
            oee=oee,
            bol_base=bol_base,
            uplift_indirect_hours=uplift_indirect_hours,
            bol=bol,
            created_by=self.created_by[:50],
        )
        result['imported'] += 1
