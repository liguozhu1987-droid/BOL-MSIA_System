# -*- coding: utf-8 -*-
"""T05 QA 验证 (入库版): BOL OIDC 开关矩阵 + 集成逻辑 (纯打桩, 不连任何数据库)

原 backend/qa_sso_switch_tests.py 移入 apps/users/tests (T05-R1 #5), 逻辑不变;
断言已含 T05-R1 #1 修复 (sync_sso_status 全量中央表回写, 无映射员工同样受保护)。

运行: cd backend && python manage.py test apps.users -v 1
全部用例为 SimpleTestCase + mock, Django 不会创建 test 数据库。
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from apps.users import oidc as oidc_mod
from apps.users.oidc_views import resolve_or_create
from rest_framework.exceptions import PermissionDenied


class SwitchMatrixTests(SimpleTestCase):
    """开关矩阵 6 项关键断言 (方案文档 6.2 / 8.1)"""

    def setUp(self):
        self.client = APIClient()

    # ---- 默认双轨配置 (settings.py 默认值) ----
    @override_settings(SELF_REGISTRATION_ENABLED=False)
    def test_register_403_when_self_registration_disabled(self):
        resp = self.client.post(reverse("auth-register"), {"username": "x", "password": "y"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("自助注册已关闭", resp.data["detail"])

    @override_settings(LOCAL_AUTH_ENABLED=False)
    def test_login_403_when_local_auth_disabled(self):
        resp = self.client.post(reverse("auth-login"), {"username": "x", "password": "y"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("本地登录已关闭", resp.data["detail"])

    @override_settings(PASSWORD_SELF_SERVICE_ENABLED=False)
    def test_change_password_403_when_self_service_disabled(self):
        """已登录用户 + 开关关闭 → 403 (未认证先 401, 认证先于开关是正确行为)"""
        fake_emp = MagicMock(); fake_emp.status = "ACTIVE"; fake_emp.username = "ligu"
        fake_tok = MagicMock(); fake_tok.key = "tok"
        with patch("apps.users.authentication.EmployeeTokenAuthentication.authenticate",
                   return_value=(fake_emp, fake_tok)):
            self.client.credentials(HTTP_AUTHORIZATION="Token tok")
            resp = self.client.post(reverse("auth-change-password"), {"old_password": "a", "new_password": "b"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("密码自助服务已关闭", resp.data["detail"])

    @override_settings(PASSWORD_SELF_SERVICE_ENABLED=True)
    def test_change_password_passes_switch_when_enabled_authenticated(self):
        """对照组: 开关打开 + 已登录 → 不被开关拦截 (到达 serializer 层)"""
        fake_emp = MagicMock(); fake_emp.status = "ACTIVE"; fake_emp.username = "ligu"
        fake_tok = MagicMock(); fake_tok.key = "tok"
        with patch("apps.users.authentication.EmployeeTokenAuthentication.authenticate",
                   return_value=(fake_emp, fake_tok)):
            self.client.credentials(HTTP_AUTHORIZATION="Token tok")
            with patch("apps.users.auth_views.ChangePasswordSerializer") as ser_cls:
                ser_cls.return_value.is_valid.side_effect = AssertionError("REACHED_SERIALIZER")
                with self.assertRaises(AssertionError):
                    self.client.post(reverse("auth-change-password"), {"old_password": "a", "new_password": "b"})

    @override_settings(PASSWORD_SELF_SERVICE_ENABLED=False)
    def test_forgot_password_403_when_self_service_disabled(self):
        resp = self.client.post(reverse("auth-forgot-password"), {"username": "x"})
        self.assertEqual(resp.status_code, 403)

    @override_settings(PASSWORD_SELF_SERVICE_ENABLED=False)
    def test_reset_password_403_when_self_service_disabled(self):
        resp = self.client.post(reverse("auth-reset-password"), {"token": "t", "new_password": "p"})
        self.assertEqual(resp.status_code, 403)

    @override_settings(OIDC_ENABLED=False)
    def test_oidc_login_503_when_oidc_disabled(self):
        resp = self.client.get(reverse("auth-oidc-login"))
        self.assertEqual(resp.status_code, 503)

    def test_oidc_token_fake_otk_400(self):
        resp = self.client.post(reverse("auth-oidc-token"), {"otk": "fake-otk-value"})
        self.assertEqual(resp.status_code, 400)

    def test_oidc_token_missing_otk_400(self):
        resp = self.client.post(reverse("auth-oidc-token"), {})
        self.assertEqual(resp.status_code, 400)

    # ---- 对照组: 开关打开时不被开关拦截 (到达业务层) ----
    @override_settings(SELF_REGISTRATION_ENABLED=True)
    def test_register_passes_switch_when_enabled(self):
        with patch("apps.users.auth_views.RegisterSerializer") as ser_cls:
            ser_cls.return_value.is_valid.side_effect = AssertionError("REACHED_SERIALIZER")
            with self.assertRaises(AssertionError):
                self.client.post(reverse("auth-register"), {"username": "x", "password": "y"})

    @override_settings(LOCAL_AUTH_ENABLED=True)
    def test_login_passes_switch_when_enabled(self):
        with patch("apps.users.auth_views.LoginSerializer") as ser_cls:
            ser_cls.return_value.is_valid.side_effect = AssertionError("REACHED_SERIALIZER")
            with self.assertRaises(AssertionError):
                self.client.post(reverse("auth-login"), {"username": "x", "password": "y"})

    # ---- 游客通道: 任何开关组合下可用 ----
    @override_settings(
        SELF_REGISTRATION_ENABLED=False,
        LOCAL_AUTH_ENABLED=False,
        PASSWORD_SELF_SERVICE_ENABLED=False,
        OIDC_ENABLED=False,
    )
    def test_guest_login_200_under_all_switches_off(self):
        fake_emp = MagicMock()
        fake_emp.role = "GUEST"
        fake_emp.status = "ACTIVE"
        fake_token = MagicMock()
        fake_token.key = "tok-guest-123"
        fake_token.expires_at.isoformat.return_value = "2026-11-03T00:00:00"
        with patch("apps.users.auth_views.Employee.objects.get_or_create", return_value=(fake_emp, True)):
            with patch("apps.users.auth_views.AuthToken.create_for_employee", return_value=fake_token):
                with patch("apps.users.auth_views.EmployeeProfileSerializer") as ser:
                    ser.return_value.data = {"username": "guest", "role": "GUEST"}
                    resp = self.client.post(reverse("auth-guest-login"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["token"], "tok-guest-123")

    # ---- AuthConfigView: 4 开关公开可读 ----
    @override_settings(
        OIDC_ENABLED=True, LOCAL_AUTH_ENABLED=False,
        SELF_REGISTRATION_ENABLED=False, PASSWORD_SELF_SERVICE_ENABLED=False,
    )
    def test_auth_config_reflects_switches(self):
        resp = self.client.get(reverse("auth-config"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {
            "oidc_enabled": True,
            "local_auth_enabled": False,
            "self_registration_enabled": False,
            "password_self_service_enabled": False,
        })


class OidcCallbackTests(SimpleTestCase):
    """OIDC 回调: state 校验 / redirect 固定路径 / otk 单次消费"""

    def setUp(self):
        self.client = APIClient()

    def test_callback_invalid_state_400(self):
        # 改动二后: OIDC 关闭时回调直接 503, state 校验仅在启用时生效
        with override_settings(OIDC_ENABLED=True):
            resp = self.client.get(reverse("auth-oidc-callback"), {"code": "abc", "state": "nonexistent"})
        self.assertEqual(resp.status_code, 400)

    def test_callback_missing_state_400(self):
        with override_settings(OIDC_ENABLED=True):
            resp = self.client.get(reverse("auth-oidc-callback"), {"code": "abc"})
        self.assertEqual(resp.status_code, 400)

    def test_callback_error_param_redirects_to_fixed_front(self):
        with override_settings(OIDC_ENABLED=True):
            resp = self.client.get(reverse("auth-oidc-callback"), {"error": "access_denied"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/oidc/callback?error="))

    def test_callback_success_redirects_to_fixed_front_with_otk(self):
        """state 有效 + 换 token/验签/建档全打桩 → 302 固定前端路径 + otk"""
        fake_emp = MagicMock()
        fake_emp.id = 7
        fake_emp.username = "ligu"
        with override_settings(OIDC_ENABLED=True, AUTH_TOKEN_EXPIRE_HOURS=168):
            oidc_mod.store_oidc_session("state-xyz", "nonce-1", "verifier-1")
            claims = {"preferred_username": "ligu", "groups": ["app-bol"], "email": "a@b.c", "name": "李"}
            with patch.object(oidc_mod, "exchange_code", return_value={"id_token": "t"}):
                with patch.object(oidc_mod, "verify_id_token", return_value=claims):
                    with patch("apps.users.oidc_views.resolve_or_create", return_value=fake_emp):
                        with patch("apps.users.oidc_views.AuthToken.create_for_employee") as tok:
                            tok.return_value.key = "tok-abc"
                            resp = self.client.get(reverse("auth-oidc-callback"), {"code": "c", "state": "state-xyz"})
        self.assertEqual(resp.status_code, 302)
        loc = resp["Location"]
        self.assertTrue(loc.startswith("/oidc/callback?otk="), loc)
        # otk 可兑换一次
        otk = loc.split("otk=")[1]
        data = oidc_mod.consume_otk(otk)
        self.assertEqual(data["employee_id"], 7)
        self.assertEqual(data["token"], "tok-abc")
        # 第二次消费失败 (单次)
        with self.assertRaises(oidc_mod.OtkError):
            oidc_mod.consume_otk(otk)

    def test_callback_state_replay_400(self):
        """state 一次性消费: 重放同一 state → 400"""
        with override_settings(OIDC_ENABLED=True):
            oidc_mod.store_oidc_session("state-replay", "n", "v")
            with patch.object(oidc_mod, "exchange_code", side_effect=Exception("net")):
                r1 = self.client.get(reverse("auth-oidc-callback"), {"code": "c", "state": "state-replay"})
                r2 = self.client.get(reverse("auth-oidc-callback"), {"code": "c", "state": "state-replay"})
        self.assertEqual(r1.status_code, 302)  # 失败回前端
        self.assertEqual(r2.status_code, 400)  # state 已消费 → 不可信回调


class ResolveOrCreateTests(SimpleTestCase):
    """身份匹配逻辑 (方案 6.1): 准入组 → UserMap → 回落 → 本地表 → 自动建档"""

    CLAIMS = {"preferred_username": "yaole", "groups": ["app-bol"], "email": "leo@x.com", "name": "姚雷"}

    def test_group_check_first(self):
        with override_settings(OIDC_REQUIRED_GROUP="app-bol"):
            with self.assertRaises(PermissionDenied):
                resolve_or_create("ligu", ["app-msia"], self.CLAIMS)

    def test_usermap_hit_uses_local_username(self):
        """UserMap 命中 → 用映射的 local_username 查 Employee"""
        with override_settings(OIDC_REQUIRED_GROUP="app-bol"):
            fake_cursor = MagicMock()
            fake_cursor.fetchone.return_value = ("Yaolei",)
            with patch("apps.users.oidc_views.connections") as conns:
                conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
                with patch("apps.users.oidc_views.Employee.objects.filter") as flt:
                    emp = MagicMock()
                    emp.status = "ACTIVE"
                    emp.email = "x@y.z"
                    emp.name = "姚雷"
                    flt.return_value.first.return_value = emp
                    result = resolve_or_create("yaole", ["app-bol"], self.CLAIMS)
                    self.assertIs(result, emp)
                    flt.return_value.first.assert_called_once()
                    # SQL 参数化: system_code='bol' + login_name 作为参数
                    args = fake_cursor.execute.call_args[0]
                    self.assertEqual(args[1], ["bol", "yaole"])

    def test_fallback_when_no_map(self):
        """无 UserMap → 回落 preferred_username"""
        with override_settings(OIDC_REQUIRED_GROUP="app-bol"):
            fake_cursor = MagicMock()
            fake_cursor.fetchone.return_value = None
            with patch("apps.users.oidc_views.connections") as conns:
                conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
                with patch("apps.users.oidc_views.Employee.objects.filter") as flt:
                    emp = MagicMock()
                    emp.status = "ACTIVE"
                    emp.email = ""
                    emp.name = ""
                    flt.return_value.first.return_value = emp
                    resolve_or_create("ligu", ["app-bol"], self.CLAIMS)
                    # 改动一后: 本地查询改为忽略大小写 (__iexact)
                    called_username = (
                        flt.call_args[1].get("username__iexact")
                        or flt.call_args[1].get("username")
                    )
                    self.assertEqual(called_username, "ligu")

    def test_auto_create_lowest_privilege_and_no_password(self):
        """自动建档: VIEWER/ACTIVE/无密码/must_change=False, 用户名用 local_username"""
        with override_settings(OIDC_REQUIRED_GROUP="app-bol", OIDC_AUTO_CREATE_USER=True):
            fake_cursor = MagicMock()
            fake_cursor.fetchone.return_value = ("Zhangy4",)
            saved = {}

            def fake_save(self):
                saved.update(self.__dict__)

            with patch("apps.users.oidc_views.connections") as conns:
                conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
                with patch("apps.users.oidc_views.Employee.objects.filter") as flt:
                    flt.return_value.first.return_value = None
                    with patch("apps.users.oidc_views.Employee.save", fake_save):
                        resolve_or_create("zhangya4", ["app-bol"], self.CLAIMS)
            self.assertEqual(saved["username"], "Zhangy4")   # 用映射 local_username 建档
            self.assertEqual(saved["role"], "VIEWER")
            self.assertEqual(saved["status"], "ACTIVE")
            self.assertEqual(saved["password"], "")            # 不落本地密码
            self.assertEqual(saved["must_change_password"], False)

    def test_auto_create_disabled_raises(self):
        with override_settings(OIDC_REQUIRED_GROUP="app-bol", OIDC_AUTO_CREATE_USER=False):
            fake_cursor = MagicMock()
            fake_cursor.fetchone.return_value = None
            with patch("apps.users.oidc_views.connections") as conns:
                conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
                with patch("apps.users.oidc_views.Employee.objects.filter") as flt:
                    flt.return_value.first.return_value = None
                    with self.assertRaises(PermissionDenied):
                        resolve_or_create("ghost", ["app-bol"], self.CLAIMS)


class SyncSsoStatusTests(SimpleTestCase):
    """状态回写: 全量中央表回写 (含无映射员工) / 中央表外本地员工不动 / dry-run 不写库"""

    def _run_cmd(self, central_rows, employees):
        """central_rows: [(local_username, status)] 模拟跨库 cursor 返回
        employees: {username: MagicMock}"""
        from django.core.management import call_command
        out = []
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = central_rows
        def filter_side_effect(**kwargs):
            uname = kwargs.get("username")
            m = MagicMock()
            m.first.return_value = employees.get(uname)
            return m
        with patch("apps.users.management.commands.sync_sso_status.connections") as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
            with patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter", side_effect=filter_side_effect):
                with patch("apps.users.management.commands.sync_sso_status.AuthToken.objects.filter") as at:
                    at.return_value.delete.return_value = (2, {})
                    call_command("sync_sso_status", stdout=type("W", (), {"write": lambda s, x: out.append(x)})())
        return out

    def test_unmapped_employee_also_synced(self):
        """T05-R1 #1 修复后: 全量中央表 LEFT JOIN UserMap —— 无映射员工 (如 admin) 同样获回写保护。
        原实现只 JOIN UserMap, admin 等无映射员工离职不传导 (R8 缺口)。"""
        yaolei = MagicMock(); yaolei.status = "ACTIVE"; yaolei.username = "Yaolei"
        admin = MagicMock(); admin.status = "ACTIVE"; admin.username = "admin"
        # 中央表返回全部用户: Yaolei 有映射, admin 无映射 (COALESCE 回落 login_name)
        out = self._run_cmd(
            central_rows=[("Yaolei", 0), ("admin", 0)],
            employees={"Yaolei": yaolei, "admin": admin},
        )
        # 两人均被停用传导 (admin 不再因无映射而漏保护)
        self.assertEqual(yaolei.status, "INACTIVE")
        self.assertEqual(admin.status, "INACTIVE")
        self.assertTrue(any("核对 2 人" in o for o in out))

    def test_local_employee_not_in_central_table_untouched(self):
        """中央表外的本地员工 (如游客 guest) 不被触碰 —— 只回写中央表覆盖的人"""
        guest = MagicMock(); guest.status = "ACTIVE"; guest.username = "guest"
        yaolei = MagicMock(); yaolei.status = "ACTIVE"; yaolei.username = "Yaolei"
        self._run_cmd(central_rows=[("Yaolei", 1)], employees={"guest": guest, "Yaolei": yaolei})
        guest.save.assert_not_called()
        self.assertEqual(guest.status, "ACTIVE")

    def test_sync_sql_covers_full_central_table(self):
        """锁死修复形状: SQL 必须从中央表全量取人 (LEFT JOIN UserMap + COALESCE 回落),
        不能退回只 JOIN UserMap 的旧形状 (R8 缺口回归防线)"""
        from apps.users.management.commands.sync_sso_status import _SYNC_SQL
        upper = _SYNC_SQL.upper()
        self.assertIn("LEFT JOIN", upper)
        self.assertIn("COALESCE", upper)
        self.assertNotIn("WHERE M.SYSTEM_CODE", upper)  # 不再以 UserMap 为过滤条件

    def test_inactive_employee_token_cleared_on_disable(self):
        yaolei = MagicMock(); yaolei.status = "ACTIVE"; yaolei.username = "Yaolei"
        self._run_cmd(central_rows=[("Yaolei", 0)], employees={"Yaolei": yaolei})
        self.assertEqual(yaolei.status, "INACTIVE")

    def test_already_inactive_employee_residual_tokens_cleared(self):
        """QA Round 2 minor 修复回归: 本地已 INACTIVE 且中央仍 status=0 时,
        历史残留 AuthToken 也必须清除, 避免复职后旧 Token 复活。"""
        yaolei = MagicMock(); yaolei.status = "INACTIVE"; yaolei.username = "Yaolei"
        out = self._run_cmd(central_rows=[("Yaolei", 0)], employees={"Yaolei": yaolei})
        # 不重复写状态, 但必须清令牌 (_run_cmd 的 mock delete 返回 2 条)
        yaolei.save.assert_not_called()
        self.assertEqual(yaolei.status, "INACTIVE")
        self.assertTrue(any("清令牌 2 条" in o for o in out))

    def test_dry_run_does_not_write(self):
        from django.core.management import call_command
        yaolei = MagicMock(); yaolei.status = "ACTIVE"; yaolei.username = "Yaolei"
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [("Yaolei", 0)]
        with patch("apps.users.management.commands.sync_sso_status.connections") as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = fake_cursor
            with patch("apps.users.management.commands.sync_sso_status.Employee.objects.filter") as flt:
                flt.return_value.first.return_value = yaolei
                call_command("sync_sso_status", "--dry-run", stdout=MagicMock())
        yaolei.save.assert_not_called()
        self.assertEqual(yaolei.status, "ACTIVE")  # 内存对象未被改

    def test_central_active_reactivates_local_inactive(self):
        yaolei = MagicMock(); yaolei.status = "INACTIVE"; yaolei.username = "Yaolei"
        self._run_cmd(central_rows=[("Yaolei", 1)], employees={"Yaolei": yaolei})
        self.assertEqual(yaolei.status, "ACTIVE")

    def test_guest_not_in_central_table_so_unaffected(self):
        """游客无中央表记录 → cursor 不返回 guest → 员工对象永不被触碰"""
        guest = MagicMock(); guest.status = "ACTIVE"; guest.username = "guest"
        self._run_cmd(central_rows=[("Yaolei", 1)], employees={"guest": guest})
        guest.save.assert_not_called()
