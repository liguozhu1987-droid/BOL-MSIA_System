# -*- coding: utf-8 -*-
"""T05 QA 验证 (入库版): MSIA OIDC 端点与开关逻辑 (直接调用端点函数, 不连数据库)

原 backend/qa_sso_verify.py 移入 tests/ (T05-R1 #5), 断言随同批修复同步更新:
- T05-R1 #2: 自动建档 Username 口径对齐 local_username (原为 preferred_username)
- T05-R1 #10: OIDC redirect 统一 302 (原断言兼容 302/307, 现收紧为仅 302)

运行: cd backend && python -m pytest tests/test_sso_oidc.py -v
"""
import base64
import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# storage 目录存在性保障 (与原 qa 脚本一致, 防止从非 backend 目录运行时模块初始化失败)
(Path(__file__).resolve().parent.parent / "storage").mkdir(exist_ok=True)

from app.core.config import settings
from app.core import oidc
from app.services import sso_identity
from app.api import auth as auth_mod
from app.schemas.auth import LoginRequest, OtkExchangeRequest


class FakeDB:
    """打桩 Session: 任意 query 返回空"""
    def query(self, *a, **k):
        return self
    def filter(self, *a, **k):
        return self
    def first(self):
        return None
    def execute(self, sql, params):
        raise AssertionError("SQL executed in test!")


class Row:
    def __init__(self, v):
        self.v = v
    def __getitem__(self, i):
        return self.v[i]


class FakeExec:
    def __init__(self, row):
        self.row = row
    def first(self):
        return self.row


class FakeDB3:
    """打桩 Session: 可控 UserMap 行与本地 User 查询结果"""
    def __init__(self, map_row, user):
        self.map_row = map_row
        self.user = user
        self.sql_params = None
    def execute(self, sql, params):
        self.sql_params = params
        return FakeExec(self.map_row)
    def query(self, model):
        outer = self
        class Q3:
            def filter(self, *a, **k):
                return self
            def first(self):
                return outer.user
        return Q3()
    def add(self, obj):
        self.added = obj
    def commit(self):
        pass
    def refresh(self, obj):
        pass


def test_auth_config_defaults():
    """/auth/config 公开端点 (config.ini: oidc=false, local=true)"""
    cfg = auth_mod.auth_config()
    assert cfg == {"oidc_enabled": False, "local_login_enabled": True}, str(cfg)


def test_oidc_login_disabled_503():
    """/oidc/login OIDC_ENABLED=false → 503"""
    with pytest.raises(HTTPException) as exc_info:
        auth_mod.oidc_login()
    assert exc_info.value.status_code == 503


def test_login_local_auth_disabled_403():
    """/login LOCAL_LOGIN_ENABLED=false → 403 (开关在查库前)"""
    with patch.object(settings, "LOCAL_LOGIN_ENABLED", False):
        with pytest.raises(HTTPException) as exc_info:
            auth_mod.login(LoginRequest(username="x", password="y"), db=FakeDB())
    assert exc_info.value.status_code == 403


def test_oidc_token_fake_otk_400():
    """/oidc/token 假 otk → 400"""
    with pytest.raises(HTTPException) as exc_info:
        auth_mod.oidc_token(OtkExchangeRequest(otk="fake-otk"), db=FakeDB())
    assert exc_info.value.status_code == 400


def test_oidc_callback_invalid_state_400():
    """oidc_callback 无效 state → 400 (改动二后: 仅 OIDC 启用时进入 state 校验)"""
    with patch.object(settings, "OIDC_ENABLED", True):
        with pytest.raises(HTTPException) as exc_info:
            auth_mod.oidc_callback(code="c", state="bogus", db=FakeDB())
    assert exc_info.value.status_code == 400


def test_oidc_callback_error_redirects_302_fixed_front():
    """oidc_callback error 参数 → 302 固定前端路径 (无开放重定向; T05-R1 #10 统一 302)"""
    with patch.object(settings, "OIDC_ENABLED", True):
        resp = auth_mod.oidc_callback(code=None, state=None, error="access_denied", db=FakeDB())
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/oidc/callback?error="), resp.headers["location"]


def test_oidc_callback_success_302_with_otk_single_use():
    """oidc_callback 成功流 (全打桩) → 302 front?otk=..., otk 单次消费"""
    fake_user = MagicMock()
    fake_user.Id = 42
    fake_user.Role = "reviewee"
    with patch.object(settings, "OIDC_ENABLED", True):
        oidc.store_oidc_session("st-1", "no-1", "ver-1")
        claims = {"preferred_username": "ligu", "groups": ["app-msia"], "email": "g@x.com", "name": "李"}
        with patch.object(oidc, "exchange_code", return_value={"id_token": "t"}), \
             patch.object(oidc, "verify_id_token", return_value=claims), \
             patch.object(auth_mod, "resolve_or_create", return_value=fake_user), \
             patch.object(auth_mod, "create_access_token", return_value="local-jwt-xyz"):
            resp = auth_mod.oidc_callback(code="c", state="st-1", db=FakeDB())
    loc = resp.headers.get("location", "")
    assert resp.status_code == 302
    assert loc.startswith("/oidc/callback?otk="), loc
    otk = loc.split("otk=")[1]
    data = oidc.consume_otk(otk)
    assert data["token"] == "local-jwt-xyz" and data["user_id"] == 42
    with pytest.raises(oidc.OtkError):
        oidc.consume_otk(otk)  # otk 单次消费 (二次失败)


def test_oidc_callback_identity_403_redirects_to_front():
    """oidc_callback 身份解析 PermissionDenied → 回前端错误页 (不回 Keycloak/不裸露)"""
    with patch.object(settings, "OIDC_ENABLED", True):
        oidc.store_oidc_session("st-2", "no-2", "ver-2")
        claims = {"preferred_username": "ghost", "groups": ["app-msia"]}
        with patch.object(oidc, "exchange_code", return_value={"id_token": "t"}), \
             patch.object(oidc, "verify_id_token", return_value=claims), \
             patch.object(auth_mod, "resolve_or_create",
                          side_effect=HTTPException(status_code=403, detail="未开通本系统访问权限")):
            resp = auth_mod.oidc_callback(code="c", state="st-2", db=FakeDB())
    assert resp.status_code == 302
    assert "?error=" in resp.headers["location"]


def test_oidc_callback_token_exchange_failure_redirects():
    """oidc_callback token 交换失败 → 回前端 (不 500)"""
    with patch.object(settings, "OIDC_ENABLED", True):
        oidc.store_oidc_session("st-3", "no-3", "ver-3")
        with patch.object(oidc, "exchange_code", side_effect=Exception("network down")):
            resp = auth_mod.oidc_callback(code="c", state="st-3", db=FakeDB())
    assert resp.status_code == 302


def test_pkce_s256_and_state_semantics():
    """PKCE / state 语义"""
    verifier, challenge = oidc.create_pkce_pair()
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expect
    oidc.store_oidc_session("s-x", "n", "v")
    item = oidc.consume_oidc_session("s-x")
    assert item["nonce"] == "n"
    with pytest.raises(KeyError):
        oidc.consume_oidc_session("s-x")  # state 重放 → KeyError


# ---- sso_identity.resolve_or_create 匹配逻辑 ----

def test_resolve_group_check_first():
    """准入组缺失 → 403 (先于 UserMap 查询)"""
    db = FakeDB3(None, None)
    with pytest.raises(HTTPException) as exc_info:
        sso_identity.resolve_or_create(db, "ligu", ["app-other-system"], {})
    assert exc_info.value.status_code == 403
    assert db.sql_params is None


def test_resolve_usermap_hit_uses_local_username():
    """UserMap 命中 → 用映射本地名; SQL 参数化"""
    u = MagicMock(); u.Status = 1; u.Email = "e@x.com"; u.DisplayName = "n"
    db = FakeDB3(Row(("Yaolei",)), u)
    with patch.object(settings, "OIDC_REQUIRED_GROUP", "app-msia"):
        got = sso_identity.resolve_or_create(db, "yaole", ["app-msia"], {"email": "a", "name": "b"})
    assert got is u
    assert db.sql_params == {"login_name": "yaole"}


def test_resolve_auto_create_uses_local_username_when_mapped():
    """T05-R1 #2: 自动建档 Username 口径 = local_username (映射命中时用映射值),
    与本地查询口径一致, 避免将来配置映射时分叉/撞唯一约束"""
    class FakeUserModel:
        Username = MagicMock()
        IsDeleted = MagicMock()
        def __init__(self, **kw):
            self.__dict__.update(kw)
    db = FakeDB3(Row(("Ligu01",)), None)  # UserMap 映射: yaole → Ligu01, 本地无此账号
    with patch.object(settings, "OIDC_REQUIRED_GROUP", "app-msia"), \
         patch.object(settings, "OIDC_AUTO_CREATE_USER", True), \
         patch.object(sso_identity, "User", FakeUserModel):
        got = sso_identity.resolve_or_create(db, "yaole", ["app-msia"], {"name": "李", "email": "g@x.com"})
    assert got.Username == "Ligu01"          # 映射 local_username, 而非 preferred_username "yaole"
    assert got.Role == "reviewee"
    assert got.Status == 1
    assert got.PasswordHash is None


def test_resolve_auto_create_fallback_when_no_map():
    """无映射回落: local_username = preferred_username"""
    class FakeUserModel:
        Username = MagicMock()
        IsDeleted = MagicMock()
        def __init__(self, **kw):
            self.__dict__.update(kw)
    db = FakeDB3(None, None)
    with patch.object(settings, "OIDC_REQUIRED_GROUP", "app-msia"), \
         patch.object(settings, "OIDC_AUTO_CREATE_USER", True), \
         patch.object(sso_identity, "User", FakeUserModel):
        got = sso_identity.resolve_or_create(db, "ligu", ["app-msia"], {"name": "李", "email": "g@x.com"})
    assert got.Username == "ligu"
    assert got.Role == "reviewee" and got.Status == 1 and got.PasswordHash is None


def test_resolve_local_disabled_user_403():
    """本地用户 Status=0 → 403"""
    u2 = MagicMock(); u2.Status = 0
    db = FakeDB3(None, u2)
    with patch.object(settings, "OIDC_REQUIRED_GROUP", "app-msia"):
        with pytest.raises(HTTPException) as exc_info:
            sso_identity.resolve_or_create(db, "yaole", ["app-msia"], {})
    assert exc_info.value.status_code == 403


def test_resolve_auto_create_disabled_403():
    """auto_create_user=false → 403 不建档"""
    with patch.object(settings, "OIDC_REQUIRED_GROUP", "app-msia"), \
         patch.object(settings, "OIDC_AUTO_CREATE_USER", False):
        with pytest.raises(HTTPException) as exc_info:
            sso_identity.resolve_or_create(FakeDB3(None, None), "ghost", ["app-msia"], {})
    assert exc_info.value.status_code == 403
