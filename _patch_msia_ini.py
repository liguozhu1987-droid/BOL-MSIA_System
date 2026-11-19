# -*- coding: utf-8 -*-
"""Insert sync switch keys into MSIA config.ini [security] section (T05-R1 #7).

Uses the same encoding detection chain as app/core/config.py
(utf-8-sig -> utf-8 -> gbk) and preserves the original encoding.
"""
P = r"MSIA Report/backend/config.ini"
ANCHOR = "local_login_enabled = true"

INSERT = """\
# 用户同步开关 (T05-R1 #7): 二者建议只开一个
# hr_sync_enabled: 每周 HRDB fine_user 全量同步 (会禁用 HR 缺失用户)
# sso_user_sync_enabled: 每日 06:30 从 CN_AME_SSO_User 派生同步
#   (只更新命中用户, 不新建/不禁用未命中; 双轨期建议 true+false,
#    P4 单轨切换后改为 false+true)
hr_sync_enabled = true
sso_user_sync_enabled = false
"""

with open(P, "rb") as f:
    raw = f.read()

text = None
enc_used = None
for enc in ("utf-8-sig", "utf-8", "gbk"):
    try:
        text = raw.decode(enc)
        enc_used = enc
        break
    except UnicodeDecodeError:
        continue
if text is None:
    raise SystemExit("config.ini encoding detection failed")

if "sso_user_sync_enabled" in text:
    print("keys already present, nothing to do")
    raise SystemExit(0)

assert text.count(ANCHOR) == 1, f"anchor not found exactly once: {ANCHOR}"

newline = "\r\n" if "\r\n" in text else "\n"
insert_block = INSERT.replace("\n", newline)
text = text.replace(ANCHOR, ANCHOR + newline + insert_block.rstrip("\r\n"), 1)

out_enc = "utf-8" if enc_used in ("utf-8-sig", "utf-8") else "gbk"
bom = b"\xef\xbb\xbf" if enc_used == "utf-8-sig" else b""
with open(P, "wb") as f:
    f.write(bom + text.encode(out_enc))

print(f"config.ini updated (encoding={enc_used}), keys inserted after '{ANCHOR}'")
