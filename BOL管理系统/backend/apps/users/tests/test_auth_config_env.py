# -*- coding: utf-8 -*-
"""BOL 认证配置环境变量覆盖测试

覆盖优先级: 环境变量 > db_config.ini > 代码默认值。
运行: cd backend && python manage.py test apps.users.tests.test_auth_config_env -v 2
"""
import io
import os
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from bol_platform import settings as s

_ENV_KEYS = list(s._AUTH_ENV_MAP.values())

_EXAMPLE_INI = """[auth]
local_auth_enabled = True
cors_allowed_origins = http://a.local, http://b.local

[oidc]
enabled = False
issuer = https://file.local/realms/inalfa
client_id = file-client
client_secret = file-secret
redirect_uri = http://file.local/cb
"""


@contextmanager
def _clean_env(**values):
    """临时清空并设置 OIDC/CORS 相关环境变量, 退出时还原"""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AuthConfigEnvOverrideTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ini = Path(self._tmp.name) / 'db_config.ini'
        self.ini.write_text(_EXAMPLE_INI, encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def _load(self, **env):
        with _clean_env(**env), patch.dict(os.environ, {'BOL_DB_CONFIG': str(self.ini)}):
            return s._load_auth_config()

    def test_env_overrides_file(self):
        """env 有值 → 覆盖文件值 (含布尔与字符串)"""
        cfg = self._load(
            OIDC_ENABLED='true',
            OIDC_ISSUER='https://env.local/realms/inalfa',
            OIDC_CLIENT_ID='env-client',
            OIDC_CLIENT_SECRET='env-secret',
            OIDC_REDIRECT_URI='https://env.local/cb',
        )
        self.assertEqual(cfg['oidc_enabled'], 'true')
        self.assertEqual(cfg['oidc_issuer'], 'https://env.local/realms/inalfa')
        self.assertEqual(cfg['oidc_client_id'], 'env-client')
        self.assertEqual(cfg['oidc_client_secret'], 'env-secret')
        self.assertEqual(cfg['oidc_redirect_uri'], 'https://env.local/cb')

    def test_env_absent_falls_back_to_file(self):
        """env 未设置 → 与仅读文件一致"""
        cfg = self._load()
        self.assertEqual(cfg['oidc_client_secret'], 'file-secret')
        self.assertEqual(cfg['oidc_client_id'], 'file-client')
        self.assertEqual(cfg['oidc_enabled'], 'False')

    def test_empty_env_does_not_override(self):
        """空字符串/纯空格 → 不覆盖, 保持文件值"""
        cfg = self._load(OIDC_CLIENT_SECRET='', OIDC_CLIENT_ID='   ')
        self.assertEqual(cfg['oidc_client_secret'], 'file-secret')
        self.assertEqual(cfg['oidc_client_id'], 'file-client')

    def test_invalid_bool_is_ignored(self):
        """非法布尔值 → 忽略环境变量并告警, 不静默改成 False/True"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            cfg = self._load(OIDC_ENABLED='maybe')
        self.assertEqual(cfg['oidc_enabled'], 'False')
        self.assertIn('不是合法布尔值', buf.getvalue())

    def test_bool_case_and_whitespace(self):
        """大小写与首尾空格应被识别为合法布尔值"""
        cfg = self._load(OIDC_ENABLED=' TrUe ')
        self.assertEqual(s._as_bool(cfg['oidc_enabled'], False), True)

    def test_cors_whitelist_from_file(self):
        """CORS 白名单键可被文件读取, 供 settings 解析"""
        cfg = self._load()
        self.assertEqual(cfg['cors_allowed_origins'], 'http://a.local, http://b.local')

    def test_env_applied_even_without_file(self):
        """没有可用配置文件时, 环境变量仍生效"""
        missing = Path(self._tmp.name) / 'missing.ini'
        with _clean_env(OIDC_CLIENT_SECRET='env-only'), \
                patch.dict(os.environ, {'BOL_DB_CONFIG': str(missing)}), \
                patch.object(s, 'BASE_DIR', Path(self._tmp.name) / 'nofile'):
            cfg = s._load_auth_config()
        self.assertEqual(cfg['oidc_client_secret'], 'env-only')
        # 未设置的键仍为代码默认值
        self.assertEqual(cfg['oidc_client_id'], 'bol-prod')
