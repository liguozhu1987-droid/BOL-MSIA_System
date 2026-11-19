#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""读取 2026 Target BOL sheet 列名"""
import pandas as pd

file_path = r'c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统\2026 Achievable BOL Summary.xlsx'

try:
    df = pd.read_excel(file_path, sheet_name='2026 Target BOL')
    print("=== 2026 Target BOL Sheet 列名 ===")
    for i, col in enumerate(df.columns, 1):
        print(f"{i}. {repr(col)}")

    print(f"\n=== 总行数: {len(df)} ===\n")
    print("=== 前5行数据预览 ===")
    print(df.head(5).to_string())
except Exception as e:
    print(f"读取失败: {e}")
    import traceback
    traceback.print_exc()
