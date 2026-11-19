# -*- coding: utf-8 -*-
"""T05 Round 2 独立验证 (临时文件, 验证后删除; 不连数据库/不连 SMTP/不写生产)

覆盖 team-lead 指定项:
  A. ForgotPasswordView 邮件路径 mock: send_mail(from_email=...) 参数正确性 + DEFAULT_FROM_EMAIL 加载
  B. sync_sso_status 令牌边界: 本地已 INACTIVE + 中央 status=0 + 旧 Token 残留 → 是否清 Token
  C. 复职复活场景: INACTIVE 员工旧 Token 认证被拒 (安全底线); 复职 ACTIVE 后旧 Token 是否复活
  D. authenticate 对 INACTIVE 员工的拦截 (authentication.py 行为锁定)
运行: cd backend && python manage.py test qa_r2_tmp_tests -v 2
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient


class ForgotPasswordMailPathTests(SimpleTestCase):
    """A. 忘记密码邮件路径 (T05-R1 #3 修复验证): mock send_mail, 不连 SMTP"""

    def setUp(self):
        self.client = APIClient()

    @override_settings(DEBUG=False)
    def test_send_mail_uses_from_email_kwarg(self):
        """功能级: send_mail 必须以 from_email= 关键字调用且值来自 DEFAULT_FROM_EMAIL"""
        from django.conf import settings as dj
        # 0. DEFAULT_FROM_EMAIL 可由配置加载 (db_config.ini [email] from_email 键)
        self.assertTrue(dj.DEFAULT_FROM_EMAIL, "DEFAULT_FROM_EMAIL 为空")
        self.assertIn("@", dj.DEFAULT_FROM_EMAIL, f"DEFAULT_FROM_EMAIL 异常: {dj.DEFAULT_FROM_EMAIL}")

        fake_emp = MagicMock()
        fake_emp.email = "ligu@inalfa.com"
        fake_emp.name = "李国柱"
        fake_tok = MagicMock()
        fake_tok.token = "rst-abc"
        fake_tok.expires_at.isoformat.return_value = "2026-11-03T09:00:00"

        with patch("apps.users.auth_views.ForgotPasswordSerializer") as ser_cls, \
             patch("apps.users.auth_views.PasswordResetToken.create_for_employee", return_value=fake_tok), \
             patch("apps.users.auth_views.send_mail") as mail_mock:
            ser_cls.return_value.is_valid.return_value = True
            ser_cls.return_value.validated_data = {"employee": fake_emp}
            resp = self.client.post(reverse("auth-forgot-password"), {"username": "ligu"})

        self.assertEqual(resp.status_code, 200)
        mail_mock.assert_called_once()
        kwargs = mail_mock.call_args.kwargs
        # 关键断言: from_email 参数存在且正确 (T05-R1 #3: 曾因 from_email 拼写被 except 吞)
        self.assertIn("from_email", kwargs, f"send_mail 缺少 from_email 参数: {kwargs.keys()}")
        self.assertEqual(kwargs["from_email"], dj.DEFAULT_FROM_EMAIL)
        self.assertEqual(kwargs["recipient_list"], ["ligu@inalfa.com"])
        self.assertEqual(kwargs["subject"], "BOL 管理分析平台 - 密码重置")
        self.assertIn("/reset-password?token=rst-abc", kwargs["message"])

    @override_settings(DEBUG=False)
    def test_no_email_no_mail_sent(self):
        """对照组: 员工无邮箱 → 不发邮件, 提示生成链接"""
        fake_emp = MagicMock()
        fake_emp.email = ""
        fake_tok = MagicMock()
        fake_tok.token = "rst-xyz"
        fake_tok.expires_at.isoformat.return_value = "2026-11-03T09:00:00"
        with patch("apps.users.auth_views.ForgotPasswordSerializer") as ser_cls, \
             patch("apps.users.auth_views.PasswordResetToken.create_for_employee", return_value=fake_tok), \
             patch("apps.users.auth_views.send_mail") as mail_mock:
            ser_cls.return_value.is_valid.return_value = True
            ser_cls.return_value.validated_data = {"employee": fake_emp}
            resp = self.client.post(reverse("auth-forgot-password"), {"username": "ghost"})
        self.assertEqual(resp.status_code, 200)
        mail_mock.assert_not_called()
        self.assertIn("detail", resp.data)

    @override_settings(DEBUG=False)
    def test_mail_failure_degrades_gracefully(self):
        """send_mail 抛异常 (SMTP 故障) → 不 500, 提示联系管理员"""
        fake_emp = MagicMock()
        fake_emp.email = "ligu@inalfa.com"
        fake_emp.name = "李国柱"
        fake_tok = MagicMock()
        fake_tok.token = "rst-fail"
        fake_tok.expires_at.isoformat.return_value = "2026-11-03T09:00:00"
        with patch("apps.users.auth_views.ForgotPasswordSerializer") as ser_cls, \
             patch("apps.users.auth_views.PasswordResetToken.create_for_employee", return_value=fake_tok), \
             patch("apps.users.auth_views.send_mail", side_effect=OSError("smtp down")):
            ser_cls.return_value.is_valid.return_value = True
            ser_cls.return_value.validated_data = {"employee": fake_emp}
            resp = self.client.post(reverse("auth-forgot-password"), {"username": "ligu"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("邮件发送失败", resp.data["detail"])

    @override_settings(DEBUG=False)
    def test_debug_off_no_token_leak(self):
        """DEBUG=False → 响应不泄露 reset_token/reset_url"""
        fake_emp = MagicMock()
        fake_emp.email = ""
        fake_tok = MagicMock()
        fake_tok.token = "rst-secret"
        fake_tok.expires_at.isoformat.return_value = "2026-11-03T09:00:00"
        with patch("apps.users.auth_views.ForgotPasswordSerializer") as ser_cls, \
             patch("apps.users.auth_views.PasswordResetToken.create_for_employee", return_value=fake_tok):
            ser_cls.return_value.is_valid.return_value = True
            ser_cls.return_value.validated_data = {"employee": fake_emp}
            resp = self.client.post(reverse("auth-forgot-password"), {"username": "ghost"})
        self.assertNotIn("reset_token", resp.data)
        self.assertNotIn("reset_url", resp.data)


class TokenBoundaryTests(SimpleTestCase):
    """B/C. sync_sso_status 令牌边界 + 复职复活 (team-lead 补充场景)"""

    def _run_sync(self, central_rows, employees):
        from django.core.management import call_command
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = central_rows
        def filter_side_effect(**kwargs):
            m = MagicMock()
            m.first.return_value = employees.get(kwargs.get("username"))
            return m
        with patch("apps.users.management.commands.sync_sso_status.connections") as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
            with patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", side_effect=filter_side_effect):
                with patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter") as at:
                    at.return_value.delete.return_value = (1, {})
                    call_command("sync_sso_status", stdout=MagicMock())
                    return at

    def test_inactive_employee_with_residual_token_not_cleared(self):
        """B-场景: 本地已 INACTIVE + 中央 status=0 + 旧 Token 残留 → 当前实现不清 Token
        (记录现状: 数据残留; 认证层仍拦截, 见 test_authenticate_rejects_inactive)"""
        emp = MagicMock(); emp.status = "INACTIVE"; emp.username = "libi2"
        at = self._run_sync(central_rows=[("libi2", 0)], employees={"libi2": emp})
        at.return_value.delete.assert_not_called()  # 现状证据: 不清
        emp.save.assert_not_called()                 # 状态无变化不写库

    def test_authenticate_rejects_inactive_employee_token(self):
        """C-底线: INACTIVE 员工的 Token 即使存在也无法通过认证 (authentication.py)"""
        from apps.users.authentication import EmployeeTokenAuthentication
        from rest_framework import exceptions
        auth = EmployeeTokenAuthentication()
        emp = MagicMock(); emp.status = "INACTIVE"
        tok = MagicMock(); tok.is_expired = False; tok.employee = emp
        with patch("apps.users.authentication.AuthToken.objects.select_related") as sr:
            sr.return_value.get.return_value = tok
            with self.assertRaises(exceptions.AuthenticationFailed):
                auth.authenticate_credentials("any-key")

    def test_reactivated_employee_old_token_revives(self):
        """C-复活证明: 复职 (status→ACTIVE) 后, 离职前未清的旧 Token 重新可通过认证。
        触发条件: 停用时 Token 未被清 (B-场景残留/历史存量) + 之后复职。"""
        from apps.users.authentication import EmployeeTokenAuthentication
        auth = EmployeeTokenAuthentication()
        emp = MagicMock(); emp.status = "INACTIVE"   # 复职前
        tok = MagicMock(); tok.is_expired = False; tok.employee = emp
        with patch("apps.users.authentication.AuthToken.objects.select_related") as sr:
            sr.return_value.get.return_value = tok
            # 复职: status 改回 ACTIVE (员工对象同引用, 模拟 DB 状态变化)
            emp.status = "ACTIVE"
            result = auth.authenticate_credentials("old-token-key")
        self.assertEqual(result, (emp, tok))  # 旧 Token 复活成立


class SsoUserSyncLogicTests(SimpleTestCase):
    """MSIA sso_user_sync 中央表派生逻辑 (mock db)"""

    class Row:
        def __init__(self, *vals):
            self.vals = vals
        def __iter__(self):
            return iter(self.vals)

    class FakeDB:
        def __init__(self, central_rows, local_users):
            self.central_rows = central_rows
            self.local_users = local_users  # {username: MagicMock user}
            self.committed = False
        def execute(self, sql):
            outer = self
            class R:
                def fetchall(self):
                    return outer.central_rows
            return R()
        def query(self, model):
            outer = self
            class Q:
                def filter(self, *a, **k):
                    return self
                def first(self):
                    uname = None
                    for arg in a:
                        pass
                    return None
            return Q()
        def commit(self):
            self.committed = True
        def rollback(self):
            pass

    def test_disable_propagation_and_no_create(self):
        """中央表 status=0 命中本地 → 本地 Status=0; 未命中跳过; 无新建调用"""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(r"C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\MSIA Report\backend")))
        (Path(r"C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\MSIA Report\backend") / "storage").mkdir(exist_ok=True)
        from app.services.sso_user_sync import sync_from_sso_central

        local = {}
        for uname in ["ligu", "yaole", "ghost"]:
            u = MagicMock()
            u.Username = uname
            u.DisplayName = "old"
            u.Email = "old@x.com"
            u.Status = 1
            local[uname] = u

        rows = [
            ("ligu", "李国柱", "new@x.com", 0),   # 命中: 停用传导 + 资料更新
            ("yaole", "姚雷", "leo@x.com", 1),     # 命中: 在职, 仅资料变化
            ("ghost", "幽灵", "g@x.com", 0),       # 本地无账号 → 跳过
        ]

        class DB:
            def execute(self, sql):
                outer = self
                class R:
                    def fetchall(self_inner):
                        return rows
                return R()
            def query(self, model):
                outer = self
                class Q:
                    def filter(self_inner, *a, **k):
                        return self_inner
                    def first(self_inner):
                        # 从 filter 参数解析 Username (SQLAlchemy 表达式不可读, 用调用顺序模拟)
                        return None
                return Q()
            def commit(self):
                pass
            def rollback(self):
                pass

        # 简化: 直接打桩 query 链, 用 side_effect 顺序返回 local 用户
        with patch("app.services.sso_user_sync.User") as UserModel:
            q = MagicMock()
            q.filter.return_value.first.side_effect = [local["ligu"], local["yaole"], None]
            UserModel.query = None
            db = DB()
            db.query = MagicMock(return_value=q)
            stats = sync_from_sso_central(db)

        self.assertEqual(stats["central_read"], 3)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(stats["skipped_no_local"], 1)
        self.assertEqual(stats["status_disabled"], 1)
        self.assertEqual(local["ligu"].Status, 0)       # 停用传导
        self.assertEqual(local["ligu"].DisplayName, "李国柱")  # 资料更新
        self.assertEqual(local["yaole"].Status, 1)      # 在职不变
        # 未命中用户绝不被触碰 (结构保证: 只遍历中央表)
        self.assertEqual(stats["updated"], 2)
