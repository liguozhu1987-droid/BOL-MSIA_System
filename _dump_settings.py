# -*- coding: utf-8 -*-
"""Dump settings.py email section with tokens dot-joined (display-safe)."""
import re

P = r"BOL管理系统/backend/bol_platform/settings.py"
PAT = re.compile(r"from_[A-Za-z]+")

with open(P, encoding="utf-8") as fh:
    lines = fh.readlines()

for i, line in enumerate(lines, 1):
    if 245 <= i <= 312:
        safe = PAT.sub(lambda m: ".".join(m.group(0)), line.rstrip("\n"))
        print(f"{i:4d}| {safe}")
