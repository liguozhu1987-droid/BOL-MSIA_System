# -*- coding: utf-8 -*-
"""Byte-level scan of from_* tokens, mangling-proof output (chars dot-joined)."""
import re

FILES = [
    r"BOL管理系统/backend/apps/users/auth_views.py",
    r"BOL管理系统/backend/apps/analytics/management/commands/send_improvement_report.py",
    r"BOL管理系统/backend/bol_platform/settings.py",
    r"BOL管理系统/backend/db_config.ini",
    r"BOL管理系统/backend/db_config.ini.example",
    r"BOL管理系统/BOLServer-Deploy-Package/db_config.ini",
    r"BOL管理系统/BOLServer-Deploy-Package/db_config.ini.example",
    r"BOL管理系统/BOLServer-Deploy-Package/_internal/db_config.ini.example",
    r"BOL管理系统/backend/dist/BOLServer/db_config.ini",
    r"BOL管理系统/backend/dist/BOLServer/_internal/db_config.ini.example",
    r"BOL管理系统/CODE_WIKI.md",
    r"BOL管理系统/backend/dist/BOLServer/_internal/apps/analytics/management/commands/send_improvement_report.py",
]

PAT = re.compile(r"from_[A-Za-z]+")

for f in FILES:
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            hits = []
            for i, line in enumerate(fh, 1):
                for m in PAT.findall(line):
                    hits.append((i, ".".join(m)))
        if hits:
            for i, tok in hits:
                print(f"{f}:{i}: {tok}")
        else:
            print(f"{f}: (no from_* tokens)")
    except FileNotFoundError:
        print(f"{f}: MISSING")

# Confirm Django's real kwarg name from vendored source
DJ = r"BOL管理系统/backend/dist/BOLServer/_internal/django/core/mail/__init__.py"
with open(DJ, encoding="utf-8") as fh:
    for i, line in enumerate(fh, 1):
        if "def send_mail" in line or "def send_mass_mail" in line:
            print(f"DJANGO-SIG {i}: {line.strip()}")
