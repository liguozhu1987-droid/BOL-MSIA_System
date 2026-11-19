#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
读取 2026 Achievable BOL Summary.xlsx 的列名
"""
import pandas as pd
import sys

file_path = r'c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统\2026 Achievable BOL Summary.xlsx'

# 读取 2026 Achievable BOL sheet
try:
    df = pd.read_excel(file_path, sheet_name='2026 Achievable BOL')
    print("=== 2026 Achievable BOL Sheet 列名 ===")
    for i, col in enumerate(df.columns, 1):
        print(f"{i}. {col}")
    
    print("\n=== 前3行数据预览 ===")
    print(df.head(3).to_string())
    
except Exception as e:
    print(f"读取失败: {e}")
    # 列出所有sheet名
    xls = pd.ExcelFile(file_path)
    print("\n可用的sheet名:")
    for sheet in xls.sheet_names:
        print(f"  - {sheet}")