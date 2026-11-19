from pathlib import Path
from openpyxl import load_workbook
p = Path(r'c:\WorkFile\D\OPEX\04-Digital_development\2026\MSIA Report\00. MSIA Check list_template.xlsx')
wb = load_workbook(p, data_only=True)
for sheet_name in ['Evaluation Standards', 'Record', 'Report MSIA1', 'Report MSIA2', 'Report MSIA3', 'Report MSIA4', 'Report MSIA5']:
    print('===', sheet_name, '===')
    ws = wb[sheet_name]
    for r in range(1, 26):
        row = [ws.cell(row=r, column=c).value for c in range(1, 21)]
        print(r, row)
    print('\n')
