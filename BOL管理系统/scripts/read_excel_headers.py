# -*- coding: utf-8 -*-
"""读取 Excel 各 sheet 的实际列名，用于重构表结构"""
from openpyxl import load_workbook

excel_path = r'c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统\2026 Achievable BOL Summary.xlsx'
wb = load_workbook(excel_path, data_only=True)

print(f'Sheets: {wb.sheetnames}')
print()

for sheet_name in wb.sheetnames:
    ws = wb[sheet_name]
    print(f'=== Sheet: {sheet_name} ===')
    print(f'  max_row={ws.max_row}, max_col={ws.max_column}')
    # 读取第1行（表头）
    headers = []
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        headers.append(f'  Col{col}: {repr(val)}')
    print('\n'.join(headers))
    # 读取第3行前几个值作为示例
    if ws.max_row >= 3:
        print('  --- Row 3 sample ---')
        for col in range(1, min(ws.max_column + 1, 24)):
            val = ws.cell(row=3, column=col).value
            print(f'  Col{col}: {repr(val)}')
    print()
