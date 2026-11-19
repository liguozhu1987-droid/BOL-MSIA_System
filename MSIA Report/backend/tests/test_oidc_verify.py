# -*- coding: utf-8 -*-
"""MSIA id_token 验签/声明校验与证书失败路径测试（不连真实 Keycloak）

运行: cd backend && python -m pytest tests/test_oidc_verify.py -v
"""
import ssl
import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from loguru import logger as loguru_logger

from app.core import oidc as oidc_mod
from app.core.config import settings

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _SigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwkClient:
    key = _PUBLIC_KEY
    error = None

    def __init__(self, url):
        pass

    def get_signing_key_from_jwt(self, token):
        if self.error is not None:
            raise self.error
        return _SigningKey(self.key)


def _claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_CLIENT_ID,
        "sub": "user-1",
        "exp": now + 300,
        "iat": now - 1,
        "nonce": "n-1",
        "preferred_username": "ligu",
    }
    claims.update(overrides)
    return claims


def _encode(claims, key=_PRIVATE_KEY, algorithm="RS256"):
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "k1"})


def _verify(token, nonce="n-1", jwk_key=None, jwk_error=None):
    with patch.object(oidc_mod, "get_discovery", return_value={"jwks_uri": "https://kc.local/jwks"}), \
            patch.object(oidc_mod.jwt, "PyJWKClient", _FakeJwkClient):
        _FakeJwkClient.key = jwk_key or _PUBLIC_KEY
        _FakeJwkClient.error = jwk_error
        return oidc_mod.verify_id_token(token, nonce)


def test_valid_token_accepted():
    claims = _verify(_encode(_claims()))
    assert claims["preferred_username"] == "ligu"


def test_wrong_issuer_rejected():
    token = _encode(_claims(iss="https://evil.local/realms/inalfa"))
    with pytest.raises(jwt.InvalidIssuerError):
        _verify(token)


def test_wrong_audience_rejected():
    token = _encode(_claims(aud="other-client"))
    with pytest.raises(jwt.InvalidAudienceError):
        _verify(token)


def test_expired_token_rejected():
    token = _encode(_claims(exp=int(time.time()) - 120))
    with pytest.raises(jwt.ExpiredSignatureError):
        _verify(token)


def test_nonce_mismatch_rejected():
    token = _encode(_claims(nonce="other-nonce"))
    with pytest.raises(ValueError, match="nonce"):
        _verify(token)


def test_missing_nonce_rejected():
    token = _encode(_claims(nonce=None))
    with pytest.raises(ValueError, match="nonce"):
        _verify(token)


def test_non_rs256_algorithm_rejected():
    token = _encode(_claims(), key="hs256-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidAlgorithmError):
        _verify(token)


def test_empty_jwks_rejected():
    error = jwt.exceptions.PyJWKClientError("Unable to find a signing key that matches")
    with pytest.raises(jwt.exceptions.PyJWKClientError):
        _verify(_encode(_claims()), jwk_error=error)


def test_signature_mismatch_rejected():
    with pytest.raises(jwt.InvalidSignatureError):
        _verify(_encode(_claims(), key=_OTHER_KEY))


def test_certificate_verify_failed_raises_readable_error():
    messages = []
    sink_id = loguru_logger.add(lambda msg: messages.append(str(msg)), level="ERROR")
    try:
        oidc_mod._discovery_cache["doc"] = None
        oidc_mod._discovery_cache["expires_at"] = 0.0
        err = ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")
        with patch.object(oidc_mod.urllib.request, "urlopen", side_effect=err):
            with pytest.raises(RuntimeError) as ctx:
                oidc_mod.get_discovery()
    finally:
        loguru_logger.remove(sink_id)
    assert "CERTIFICATE_VERIFY_FAILED" in str(ctx.value)
    # 日志走 loguru, 用临时 sink 断言
    assert any("证书校验失败" in m for m in messages)
