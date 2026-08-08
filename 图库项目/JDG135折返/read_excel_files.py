import openpyxl
import os
from pathlib import Path

folder = Path(r"D:\xwechat_files\wxid_8trx0rxyrqr822_4a9b\msg\file\2026-06\????\JDG135??")
files = [
    "??.xlsx",
    "????.xlsx",
    "??.xlsx",
    "?????.xlsx",
    "????.xlsx",
    "??????.xlsx"
]

for fname in files:
    fpath = folder / fname
    print(f"\n{'='*60}")
    print(f"FILE: {fname}")
    print('='*60)
    wb = openpyxl.load_workbook(str(fpath), data_only=True)
    for sheet_name in wb.sheetnames:
        print(f"\n--- Sheet: {sheet_name} ---")
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            if any(cell is not None for cell in row):
                print(row)
