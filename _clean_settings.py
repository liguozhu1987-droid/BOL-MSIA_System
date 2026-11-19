# -*- coding: utf-8 -*-
"""Remove the dead-code legacy-key shim from settings.py (T05-R1 #3 closure).

Background: the 'spelling incident' reported by QA was a display-layer
artifact - byte-level scans (od -c / char-joined dumps) prove every
from-email token on disk is already the CORRECT Django name, in both the
staged (pre-T05) originals and the current worktree. The compat shim added
earlier was based on that artifact and its condition is always False.
This script removes it, restoring the simple correct loader.
"""
P = r"BOL管理系统/backend/bol_platform/settings.py"
T = "from_" + "email"  # built via concatenation: immune to display mangling

with open(P, encoding="utf-8") as fh:
    src = fh.read()

OLD_DOC = (
    '    """从 db_config.ini [email] 段读取邮件配置，覆盖默认值\n'
    "\n"
    "    兼容存量配置: 旧版 ini 使用拼写错误的键名 " + T + " (T05-R1 #3 修复),\n"
    "    读取时 " + T + " 优先、" + T + " 兜底, 防止生产存量 ini 失效。\n"
    '    """\n'
)
NEW_DOC = '    """从 db_config.ini [email] 段读取邮件配置，覆盖默认值"""\n'

OLD_SHIM = (
    "                    # 兼容存量 ini 的旧键名 " + T + " (仅当新键名缺失时兜底)\n"
    "                    if (not parser.has_option('email', '" + T + "')\n"
    "                            and parser.has_option('email', '" + T + "')):\n"
    "                        cfg['" + T + "'] = parser.get('email', '" + T + "').strip()\n"
    "                        print('[settings] 检测到旧键名 " + T + ", 已兼容读取 (建议改为 " + T + ")')\n"
)
NEW_SHIM = ""

assert src.count(OLD_DOC) == 1, "docstring block not found exactly once"
assert src.count(OLD_SHIM) == 1, "shim block not found exactly once"

src = src.replace(OLD_DOC, NEW_DOC)
src = src.replace(OLD_SHIM, NEW_SHIM)

with open(P, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)

print("settings.py cleaned: dead shim removed, docstring simplified")

# Verify: re-dump the section safely
import re
PAT = re.compile(r"from_[A-Za-z]+")
with open(P, encoding="utf-8") as fh:
    lines = fh.readlines()
for i, line in enumerate(lines, 1):
    if 258 <= i <= 300:
        safe = PAT.sub(lambda m: ".".join(m.group(0)), line.rstrip("\n"))
        print(f"{i:4d}| {safe}")
