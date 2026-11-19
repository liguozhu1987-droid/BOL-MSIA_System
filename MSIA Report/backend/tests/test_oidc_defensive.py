# -*- coding: utf-8 -*-
"""防御性改动回归 (MSIA): 改动一 大小写不敏感身份解析 + 建档前查重; 改动二 配置体检

运行: cd backend && python -m pytest tests -q
"""
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
(Path(__file__).resolve().parent.parent / "storage").mkdir(exist_ok=True)

from app.api import auth as auth_mod
from app.core import oidc
from app.core.config import settings
from app.schemas.auth import LoginRequest
from app.services import sso_identity

VALID_OIDC = dict(
    OIDC_ENABLED=True,
    OIDC_ISSUER="https://sso.ap.inalfa.local/realms/inalfa",
    OIDC_CLIENT_ID="msia-prod",
    OIDC_CLIENT_SECRET="s3cret-value",
    OIDC_REDIRECT_URI="https://sso.ap.inalfa.local/api/auth/oidc/callback",
)


@contextmanager
def _settings(**kwargs):
    """临时覆盖 pydantic settings 字段"""
    with patch.multiple(settings, **kwargs):
        yield


@contextmanager
def _capture_logs(level="INFO"):
    """捕获 loguru 日志 (项目日志不走 stdlib logging)"""
    records = []
    sink_id = logger.add(lambda m: records.append(str(m)), level=level)
    try:
        yield records
    finally:
        logger.remove(sink_id)


class FakeDB:
    """打桩 Session: 依次弹出 query 结果; 记录 add/rollback 调用"""

    def __init__(self, map_row=None, users=None):
        self.map_row = map_row
        self.users = list(users or [])
        self.added = []
        self.sql_params = None
        self.commit_count = 0
        self.rolled_back = False

    def execute(self, sql, params):
        self.sql_params = params
        return _FakeExec(self.map_row)

    def query(self, model):
        outer = self

        class _Q:
            def filter(self, *a, **k):
                return self

            def first(self):
                return outer.users.pop(0) if outer.users else None

        return _Q()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        pass


class _Row:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, i):
        return self.value[i]


class _FakeExec:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class FakeUserModel:
    """替身 User 模型 (只用于构造建档对象)"""
    Username = MagicMock()
    IsDeleted = MagicMock()

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestUserMapSql:
    def test_usermap_sql_uses_upper_without_hardcoded_collation(self):
        sql = str(sso_identity._USERMAP_SQL).upper()
        assert "UPPER(" in sql
        assert "LTRIM(" in sql
        assert "COLLATE" not in sql  # 不写死某个 collation
        assert "LOWER(" not in sql


class TestCaseInsensitiveMatch:
    def test_usermap_param_keeps_original_case(self):
        db = FakeDB(None, users=[None, None])
        with _settings(OIDC_REQUIRED_GROUP="app-msia", OIDC_AUTO_CREATE_USER=True), \
             patch.object(sso_identity, "User", FakeUserModel):
            sso_identity.resolve_or_create(db, "Yaolei", ["app-msia"], {"name": "姚雷"})
        assert db.sql_params == {"login_name": "Yaolei"}

    def test_cs_collation_case_diff_hits_existing_and_never_creates(self):
        """模拟 _CS_: 主查询未命中, 建档前查重命中 -> 复用, 不调用 db.add"""
        existing = MagicMock()
        existing.Status = 1
        existing.Username = "Yaolei"
        existing.Email = "leo@x.com"
        existing.DisplayName = "姚雷"
        db = FakeDB(None, users=[None, existing])  # 主查询 None, 查重命中
        with _settings(OIDC_REQUIRED_GROUP="app-msia", OIDC_AUTO_CREATE_USER=True), \
             _capture_logs() as logs:
            got = sso_identity.resolve_or_create(db, "yaolei", ["app-msia"], {})
        assert got is existing
        assert db.added == []  # 关键: 没有 create
        assert any("大小写差异命中" in line for line in logs)

    def test_auto_create_keeps_original_case(self):
        db = FakeDB(None, users=[None, None])
        with _settings(OIDC_REQUIRED_GROUP="app-msia", OIDC_AUTO_CREATE_USER=True), \
             patch.object(sso_identity, "User", FakeUserModel):
            got = sso_identity.resolve_or_create(db, "Yaolei", ["app-msia"], {"name": "姚雷", "email": "leo@x.com"})
        assert len(db.added) == 1
        assert got.Username == "Yaolei"  # 保持原样大小写, 不强制 lower
        assert got.Role == "reviewee" and got.Status == 1 and got.PasswordHash is None

    def test_unique_index_conflict_falls_back_to_existing(self):
        """CI 排序规则下撞唯一索引: 回滚后回查复用, 不冒泡 500"""
        from sqlalchemy.exc import IntegrityError

        existing = MagicMock()
        existing.Status = 1
        existing.Username = "Yaolei"
        existing.Email = "leo@x.com"
        existing.DisplayName = "姚雷"
        db = FakeDB(None, users=[None, None, existing])

        def _commit_raises():
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        db.commit = _commit_raises
        with _settings(OIDC_REQUIRED_GROUP="app-msia", OIDC_AUTO_CREATE_USER=True), \
             patch.object(sso_identity, "User", FakeUserModel):
            got = sso_identity.resolve_or_create(db, "Yaolei", ["app-msia"], {})
        assert got is existing
        assert db.rolled_back is True


class TestOidcConfigValidation:
    def test_empty_client_secret_is_error(self):
        with _settings(**{**VALID_OIDC, "OIDC_CLIENT_SECRET": ""}):
            result = oidc.validate_config()
        assert any("client_secret" in e and "(空)" in e for e in result["errors"]), result

    def test_placeholder_redirect_is_error(self):
        with _settings(**{**VALID_OIDC,
                          "OIDC_REDIRECT_URI": "http://127.0.0.1:8078/api/auth/oidc/callback"}):
            result = oidc.validate_config()
        assert any("127.0.0.1" in e and "redirect_uri" in e for e in result["errors"]), result

    def test_issuer_redirect_host_mismatch_is_error(self):
        with _settings(**{**VALID_OIDC,
                          "OIDC_REDIRECT_URI": "http://172.26.2.203:8078/api/auth/oidc/callback"}):
            result = oidc.validate_config()
        assert any(
            "sso.ap.inalfa.local" in e and "172.26.2.203" in e for e in result["errors"]
        ), result

    def test_non_https_issuer_is_error(self):
        with _settings(**{**VALID_OIDC,
                          "OIDC_ISSUER": "http://sso.ap.inalfa.local/realms/inalfa",
                          "OIDC_REDIRECT_URI": "http://sso.ap.inalfa.local/api/auth/oidc/callback"}):
            result = oidc.validate_config()
        assert any("不是 https" in e for e in result["errors"]), result

    def test_disabled_only_one_info(self):
        with _settings(OIDC_ENABLED=False):
            result = oidc.validate_config()
        assert result["errors"] == []
        assert result["warnings"] == []
        assert len(result["info"]) == 1


class TestOidcLoginConfigGate:
    def test_login_503_with_readable_message_when_config_incomplete(self):
        with _settings(**{**VALID_OIDC, "OIDC_CLIENT_SECRET": ""}):
            with pytest.raises(HTTPException) as exc_info:
                auth_mod.oidc_login()
        assert exc_info.value.status_code == 503
        assert "OIDC 配置不完整" in exc_info.value.detail
        assert "client_secret" in exc_info.value.detail

    def test_login_302_when_config_valid(self):
        with _settings(**VALID_OIDC), patch.object(oidc, "build_authorize_url",
                                                  return_value="https://sso.ap.inalfa.local/auth"):
            resp = auth_mod.oidc_login()
        assert resp.status_code == 302

    def test_callback_503_when_disabled(self):
        with _settings(OIDC_ENABLED=False):
            with pytest.raises(HTTPException) as exc_info:
                auth_mod.oidc_callback(code="c", state="s", db=FakeDB())
        assert exc_info.value.status_code == 503

    def test_local_login_unaffected_when_oidc_disabled(self):
        """双轨期: OIDC 关闭不影响本地账密登录 (仍走到用户查询)"""
        with _settings(OIDC_ENABLED=False):
            with pytest.raises(HTTPException) as exc_info:
                auth_mod.login(LoginRequest(username="x", password="y"), db=FakeDB())
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "用户名或密码错误"
