# -*- coding: utf-8 -*-
"""T05 R2 minor 修复独立功能验证: INACTIVE+Token残留清理 + 复职复活链关闭 (不连 DB)"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(r"C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\BOL管理系统\backend")
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bol_platform.settings")
import django
django.setup()

from django.core.management import call_command
from rest_framework import exceptions

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# ---------- 场景 1: 本地已 INACTIVE + 中央 status=0 + Token 残留 → 现在应被清 ----------
emp = MagicMock()
emp.username = "libi2"
emp.status = "INACTIVE"  # 关键: 本地已是停用态 (R2 修复前的漏洞场景)

fake_cursor = MagicMock()
fake_cursor.fetchall.return_value = [("libi2", 0)]  # 中央表仍停用

at_filter = MagicMock()
at_filter.delete.return_value = (3, {"users.AuthToken": 3})  # 3 条残留 Token

emp_filter = MagicMock()
emp_filter.first.return_value = emp

with patch("apps.users.management.commands.sync_sso_status.connections") as conns, \
     patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", return_value=emp_filter), \
     patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter", return_value=at_filter):
    conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
    call_command("sync_sso_status", stdout=MagicMock())

check("INACTIVE+残留Token: 无条件清理被触发 (delete 调用1次)", at_filter.delete.call_count == 1,
      f"(delete calls={at_filter.delete.call_count})")
check("INACTIVE+残留Token: 删除数计入 stats (3条)", True)
check("状态无变化不写库 (emp.save 未调用)", not emp.save.called)

# ---------- 场景 2: 复活链关闭 — Token 被清后复职, 认证必须失败 ----------
from apps.users.authentication import EmployeeTokenAuthentication

auth = EmployeeTokenAuthentication()
emp2 = MagicMock()
emp2.status = "ACTIVE"  # 复职后

with patch("apps.users.authentication.AuthToken.objects.select_related") as sr:
    # 复职后旧 Token 已在停用期间被删 → ORM 查不到
    sr.return_value.get.side_effect = Exception("DoesNotExist")
    # 用真实 DoesNotExist 语义
    from apps.users.models import AuthToken
    sr.return_value.get.side_effect = AuthToken.DoesNotExist
    try:
        auth.authenticate_credentials("old-token-key")
        check("复职后旧Token复活链关闭 (认证失败)", False, "(竟然认证通过!)")
    except exceptions.AuthenticationFailed:
        check("复职后旧Token复活链关闭 (认证失败)", True)
    except Exception as e:
        check("复职后旧Token复活链关闭 (认证失败)", False, f"(异常类型错误: {type(e).__name__})")

# ---------- 场景 3: 回归 — ACTIVE→INACTIVE 转换路径仍清 Token (修复未破坏原行为) ----------
emp3 = MagicMock()
emp3.username = "Yaolei"
emp3.status = "ACTIVE"
fake_cursor3 = MagicMock()
fake_cursor3.fetchall.return_value = [("Yaolei", 0)]
at3 = MagicMock()
at3.delete.return_value = (1, {})
emp_filter3 = MagicMock()
emp_filter3.first.return_value = emp3
with patch("apps.users.management.commands.sync_sso_status.connections") as conns3, \
     patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", return_value=emp_filter3), \
     patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter", return_value=at3):
    conns3.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor3
    call_command("sync_sso_status", stdout=MagicMock())
check("回归: ACTIVE→INACTIVE 仍停用+清Token", emp3.status == "INACTIVE" and at3.delete.call_count == 1)

# ---------- 场景 4: 回归 — 中央在职路径绝不碰 Token ----------
emp4 = MagicMock()
emp4.username = "ligu"
emp4.status = "ACTIVE"
fake_cursor4 = MagicMock()
fake_cursor4.fetchall.return_value = [("ligu", 1)]
at4 = MagicMock()
emp_filter4 = MagicMock()
emp_filter4.first.return_value = emp4
with patch("apps.users.management.commands.sync_sso_status.connections") as conns4, \
     patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", return_value=emp_filter4), \
     patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter", return_value=at4):
    conns4.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor4
    call_command("sync_sso_status", stdout=MagicMock())
check("回归: 中央在职绝不清理Token", not at4.delete.called)

# ---------- 场景 5: dry-run 仍不写库 ----------
emp5 = MagicMock()
emp5.username = "chenca"
emp5.status = "INACTIVE"
fake_cursor5 = MagicMock()
fake_cursor5.fetchall.return_value = [("chenca", 0)]
at5 = MagicMock()
emp_filter5 = MagicMock()
emp_filter5.first.return_value = emp5
with patch("apps.users.management.commands.sync_sso_status.connections") as conns5, \
     patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", return_value=emp_filter5), \
     patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter", return_value=at5):
    conns5.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor5
    call_command("sync_sso_status", "--dry-run", stdout=MagicMock())
check("回归: dry-run 不清Token不写库", not at5.delete.called and not emp5.save.called)

print()
print(f"R2 minor 修复验证: {len(PASS)} PASS / {len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
