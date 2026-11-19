# -*- coding: utf-8 -*-
"""防御性改动回归 (改动一: 大小写不敏感身份解析 + 建档前查重; 改动二: 配置体检)

运行: cd backend && python manage.py test apps.users -v 1
全部用例为 SimpleTestCase + mock, Django 不会创建 test 数据库。
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users import oidc as oidc_mod
from apps.users.oidc_views import _USERMAP_SQL, resolve_or_create

CLAIMS = {"email": "leo@x.com", "name": "姚雷"}

# 一份"配置完整"的 OIDC 基线 (issuer 与 redirect_uri 主机一致, secret 非空)
VALID_OIDC = dict(
    OIDC_ENABLED=True,
    OIDC_ISSUER="https://sso.ap.inalfa.local/realms/inalfa",
    OIDC_CLIENT_ID="bol-prod",
    OIDC_CLIENT_SECRET="s3cret-value",
    OIDC_REDIRECT_URI="https://sso.ap.inalfa.local/api/auth/oidc/callback",
)


def _qs(found):
    """构造一个 filter() 返回的 QuerySet 打桩 (first() 返回 found)"""
    m = MagicMock()
    m.first.return_value = found
    return m


def _cursor(row):
    cur = MagicMock()
    cur.fetchone.return_value = row
    return cur


@contextmanager
def _patch_db(row):
    """打桩跨库 cursor (UserMap 查询)"""
    with patch("apps.users.oidc_views.connections") as conns:
        conns.__getitem__.return_value.cursor.return_value.__enter__.return_value = _cursor(row)
        yield conns


class UserMapCaseInsensitiveTests(SimpleTestCase):
    """改动一: UserMap 查询不写死 collation, 两侧 UPPER() 比对"""

    def test_usermap_sql_uses_upper_and_no_hardcoded_collation(self):
        sql = _USERMAP_SQL.upper()
        self.assertIn("UPPER(", sql)
        self.assertIn("LTRIM(", sql)
        self.assertNotIn("COLLATE", sql)  # 不写死某个 collation
        self.assertNotIn("LOWER(", sql)

    @override_settings(OIDC_REQUIRED_GROUP="app-bol")
    def test_param_keeps_original_case(self):
        """SQL 参数保留原始大小写 (比对在 SQL 侧忽略大小写)"""
        with _patch_db(None) as conns:
            with patch("apps.users.oidc_views.Employee") as emp_cls:
                emp_cls.objects.filter.return_value = _qs(None)
                resolve_or_create("Yaolei", ["app-bol"], CLAIMS)
        args = conns.__getitem__.return_value.cursor.return_value.__enter__.return_value.execute.call_args[0]
        self.assertEqual(args[1], ["bol", "Yaolei"])

    @override_settings(OIDC_REQUIRED_GROUP="app-bol")
    def test_local_lookup_is_iexact(self):
        """本地 Employee 查询必须走 __iexact"""
        emp = MagicMock(status="ACTIVE", email="e@x.com", name="姚雷", username="Yaolei")
        with _patch_db(None):
            with patch("apps.users.oidc_views.Employee.objects.filter") as flt:
                flt.return_value = _qs(emp)
                got = resolve_or_create("yaolei", ["app-bol"], CLAIMS)
        self.assertIs(got, emp)
        self.assertEqual(flt.call_args[1]["username__iexact"], "yaolei")


class PreCreateDedupTests(SimpleTestCase):
    """改动一: 建档前忽略大小写查重, 命中则复用且绝不新建"""

    @override_settings(OIDC_REQUIRED_GROUP="app-bol", OIDC_AUTO_CREATE_USER=True)
    def test_cs_collation_case_diff_hits_existing_and_never_creates(self):
        """模拟 _CS_ 排序规则: 主查询未命中, 建档前查重命中 -> 复用, 不构造 Employee"""
        existing = MagicMock(status="ACTIVE", email="e@x.com", name="姚雷", username="Yaolei")
        with _patch_db(None):
            with patch("apps.users.oidc_views.Employee") as emp_cls:
                # 第一次 = 主查询 (未命中); 第二次 = 建档前查重 (命中)
                emp_cls.objects.filter.side_effect = [_qs(None), _qs(existing)]
                with self.assertLogs("apps.users.oidc_views", level="INFO") as logs:
                    got = resolve_or_create("yaolei", ["app-bol"], CLAIMS)
        self.assertIs(got, existing)
        emp_cls.assert_not_called()  # 关键: 没有调用 create
        self.assertEqual(emp_cls.objects.filter.call_count, 2)
        self.assertTrue(any("大小写差异命中" in line for line in logs.output))

    @override_settings(OIDC_REQUIRED_GROUP="app-bol", OIDC_AUTO_CREATE_USER=True)
    def test_auto_create_keeps_original_case(self):
        """确实需要建档时, 用户名保持原样大小写 (不强制 lower)"""
        with _patch_db(("Zhangy4",)):
            with patch("apps.users.oidc_views.Employee") as emp_cls:
                emp_cls.objects.filter.return_value = _qs(None)
                resolve_or_create("zhangy4", ["app-bol"], CLAIMS)
        emp_cls.assert_called_once()
        kwargs = emp_cls.call_args[1]
        self.assertEqual(kwargs["username"], "Zhangy4")  # 用映射值原样大小写
        self.assertEqual(kwargs["role"], "VIEWER")
        self.assertEqual(kwargs["password"], "")

    @override_settings(OIDC_REQUIRED_GROUP="app-bol", OIDC_AUTO_CREATE_USER=True)
    def test_unique_index_conflict_falls_back_to_existing(self):
        """CONF 排序规则下并发/撞唯一索引: 回查复用, 不冒泡 500"""
        existing = MagicMock(status="ACTIVE", email="e@x.com", name="姚雷", username="Yaolei")
        with _patch_db(None):
            with patch("apps.users.oidc_views.Employee") as emp_cls:
                emp_cls.objects.filter.side_effect = [_qs(None), _qs(None), _qs(existing)]
                emp_cls.return_value.save.side_effect = IntegrityError("duplicate username")
                got = resolve_or_create("Yaolei", ["app-bol"], CLAIMS)
        self.assertIs(got, existing)


class OidcConfigValidationTests(SimpleTestCase):
    """改动二: 配置体检 fail loud (四种命中各一条)"""

    def test_empty_client_secret_is_error(self):
        with override_settings(**{**VALID_OIDC, "OIDC_CLIENT_SECRET": ""}):
            result = oidc_mod.validate_config()
        self.assertTrue(result["errors"])
        self.assertTrue(any("client_secret" in e and "(空)" in e for e in result["errors"]), result)

    def test_placeholder_redirect_is_error(self):
        with override_settings(**{**VALID_OIDC,
                                  "OIDC_REDIRECT_URI": "http://127.0.0.1:8090/api/auth/oidc/callback"}):
            result = oidc_mod.validate_config()
        self.assertTrue(any("127.0.0.1" in e and "redirect_uri" in e for e in result["errors"]), result)

    def test_issuer_redirect_host_mismatch_is_error(self):
        with override_settings(**{**VALID_OIDC,
                                  "OIDC_REDIRECT_URI": "https://172.26.2.203:8090/api/auth/oidc/callback"}):
            result = oidc_mod.validate_config()
        self.assertTrue(
            any("sso.ap.inalfa.local" in e and "172.26.2.203" in e for e in result["errors"]),
            result,
        )

    def test_non_https_issuer_is_error(self):
        with override_settings(**{**VALID_OIDC,
                                  "OIDC_ISSUER": "http://sso.ap.inalfa.local/realms/inalfa",
                                  "OIDC_REDIRECT_URI": "http://sso.ap.inalfa.local/api/auth/oidc/callback"}):
            result = oidc_mod.validate_config()
        self.assertTrue(any("不是 https" in e for e in result["errors"]), result)

    def test_secret_is_masked_in_message(self):
        with override_settings(**VALID_OIDC):
            result = oidc_mod.validate_config()
        self.assertEqual(result["errors"], [])  # 完整配置无 error
        masked = oidc_mod.mask_secret("s3cret-value")
        self.assertNotIn("s3cret-value", masked)  # 不泄漏明文
        self.assertIn("***", masked)

    @override_settings(OIDC_ENABLED=False)
    def test_disabled_only_one_info(self):
        result = oidc_mod.validate_config()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["info"]), 1)


class OidcLoginConfigGateTests(SimpleTestCase):
    """改动二: 登录端点 503 (可读提示) 而非 500 traceback"""

    def setUp(self):
        self.client = APIClient()

    def test_login_503_with_readable_message_when_config_incomplete(self):
        with override_settings(**{**VALID_OIDC, "OIDC_CLIENT_SECRET": ""}):
            resp = self.client.get(reverse("auth-oidc-login"))
        self.assertEqual(resp.status_code, 503)
        body = resp.content.decode("utf-8")
        self.assertIn("OIDC 配置不完整", body)
        self.assertIn("client_secret", body)

    def test_login_302_when_config_valid(self):
        with override_settings(**VALID_OIDC):
            with patch.object(oidc_mod, "build_authorize_url", return_value="https://sso.ap.inalfa.local/auth"):
                resp = self.client.get(reverse("auth-oidc-login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://sso.ap.inalfa.local/auth")

    @override_settings(OIDC_ENABLED=False)
    def test_callback_503_when_disabled(self):
        resp = self.client.get(reverse("auth-oidc-callback"), {"code": "c", "state": "s"})
        self.assertEqual(resp.status_code, 503)

    @override_settings(OIDC_ENABLED=False)
    def test_local_login_unaffected_when_oidc_disabled(self):
        """双轨期: OIDC 关闭不影响本地账密登录路径 (仍到达 serializer)"""
        with patch("apps.users.auth_views.LoginSerializer") as ser:
            ser.return_value.is_valid.side_effect = AssertionError("REACHED_SERIALIZER")
            with self.assertRaises(AssertionError):
                self.client.post(reverse("auth-login"), {"username": "x", "password": "y"})
