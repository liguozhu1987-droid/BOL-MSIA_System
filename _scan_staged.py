# -*- coding: utf-8 -*-
"""Safe scan of STAGED (original) versions + QA report files."""
import re
import subprocess

PAT = re.compile(r"from_[A-Za-z]+")

STAGED_FILES = [
    "backend/apps/users/auth_views.py",
    "backend/apps/analytics/management/commands/send_improvement_report.py",
    "backend/bol_platform/settings.py",
    "backend/db_config.ini",
    "backend/db_config.ini.example",
    "BOLServer-Deploy-Package/db_config.ini",
]

repo = r"BOL管理系统"

for rel in STAGED_FILES:
    try:
        out = subprocess.run(
            ["git", "show", f":{rel}"],
            cwd=repo, capture_output=True,
        ).stdout.decode("utf-8", errors="replace")
        hits = []
        for i, line in enumerate(out.splitlines(), 1):
            for m in PAT.findall(line):
                hits.append((i, ".".join(m)))
        if hits:
            for i, tok in hits:
                print(f"STAGED {rel}:{i}: {tok}")
        else:
            print(f"STAGED {rel}: (no from_* tokens)")
    except Exception as e:
        print(f"STAGED {rel}: ERROR {e}")

# QA report / implementation docs on disk
import os
DOC_DIRS = ["统一身份认证实施"]
for d in DOC_DIRS:
    if not os.path.isdir(d):
        continue
    for root, _dirs, files in os.walk(d):
        for name in files:
            if not name.endswith((".md", ".txt", ".py")):
                continue
            p = os.path.join(root, name)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        for m in PAT.findall(line):
                            print(f"DOC {p}:{i}: {'.'.join(m)}")
                        # also look for the literal weird token as it might be typed
                        if "hiuwy" in line:
                            print(f"DOC-LITERAL {p}:{i}: contains_hiuwy_token")
            except Exception:
                pass
