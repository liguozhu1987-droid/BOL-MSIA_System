# -*- coding: utf-8 -*-
"""BOL id_token 验签/声明校验与证书失败路径测试 (不连真实 Keycloak)

覆盖: JWKS 正常/空 keys/算法非 RS256/签名不匹配; iss/aud/exp/nonce 拒绝;
证书校验失败时抛 OidcError 并写 ERROR 日志; UserMap 缺失回落建档风险。

运行: cd backend && python manage.py test apps.users.tests.test_oidc_token_verify -v 2
"""
import ssl
import time
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.users import oidc as oidc_mod
from apps.users.oidc_views import resolve_or_create
from rest_framework.exceptions import PermissionDenied

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _SigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwkClient:
    """替代 jwt.PyJWKClient: 固定返回公钥或抛出指定异常"""
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
        'iss': settings.OIDC_ISSUER,
        'aud': settings.OIDC_CLIENT_ID,
        'sub': 'user-1',
        'exp': now + 300,
        'iat': now - 1,
        'nonce': 'n-1',
        'preferred_username': 'ligu',
    }
    claims.update(overrides)
    return claims


def _encode(claims, key=_PRIVATE_KEY, algorithm='RS256'):
    return jwt.encode(claims, key, algorithm=algorithm, headers={'kid': 'k1'})


class IdTokenVerifyTests(SimpleTestCase):
    def _verify(self, token, nonce='n-1', jwk_key=None, jwk_error=None):
        with patch.object(oidc_mod, 'get_discovery', return_value={'jwks_uri': 'https://kc.local/jwks'}), \
                patch.object(oidc_mod.jwt, 'PyJWKClient', _FakeJwkClient):
            _FakeJwkClient.key = jwk_key or _PUBLIC_KEY
            _FakeJwkClient.error = jwk_error
            return oidc_mod.verify_id_token(token, nonce)

    def test_valid_token_accepted(self):
        claims = self._verify(_encode(_claims()))
        self.assertEqual(claims['preferred_username'], 'ligu')

    def test_wrong_issuer_rejected(self):
        token = _encode(_claims(iss='https://evil.local/realms/inalfa'))
        with self.assertRaises(jwt.InvalidIssuerError):
            self._verify(token)

    def test_wrong_audience_rejected(self):
        token = _encode(_claims(aud='other-client'))
        with self.assertRaises(jwt.InvalidAudienceError):
            self._verify(token)

    def test_expired_token_rejected(self):
        token = _encode(_claims(exp=int(time.time()) - 120))  # 超出 60s leeway
        with self.assertRaises(jwt.ExpiredSignatureError):
            self._verify(token)

    def test_nonce_mismatch_rejected(self):
        token = _encode(_claims(nonce='other-nonce'))
        with self.assertRaisesRegex(ValueError, 'nonce'):
            self._verify(token, nonce='n-1')

    def test_missing_nonce_rejected(self):
        token = _encode(_claims(nonce=None))
        with self.assertRaisesRegex(ValueError, 'nonce'):
            self._verify(token, nonce='n-1')

    def test_non_rs256_algorithm_rejected(self):
        token = _encode(_claims(), key='hs256-secret', algorithm='HS256')
        with self.assertRaises(jwt.InvalidAlgorithmError):
            self._verify(token)

    def test_empty_jwks_rejected(self):
        """JWKS 无匹配 kid (空 keys) → PyJWKClientError, 不返回 claims"""
        error = jwt.exceptions.PyJWKClientError('Unable to find a signing key that matches')
        with self.assertRaises(jwt.exceptions.PyJWKClientError):
            self._verify(_encode(_claims()), jwk_error=error)

    def test_signature_mismatch_rejected(self):
        token = _encode(_claims(), key=_OTHER_KEY)
        with self.assertRaises(jwt.InvalidSignatureError):
            self._verify(token)


class CertificateFailureTests(SimpleTestCase):
    def setUp(self):
        oidc_mod._discovery_cache['doc'] = None
        oidc_mod._discovery_cache['expires_at'] = 0.0

    def tearDown(self):
        oidc_mod._discovery_cache['doc'] = None
        oidc_mod._discovery_cache['expires_at'] = 0.0

    def test_certificate_verify_failed_raises_readable_error(self):
        """自签证书握手失败 → OidcError 且日志含 CERTIFICATE_VERIFY_FAILED"""
        err = ssl.SSLCertVerificationError(1, 'CERTIFICATE_VERIFY_FAILED')
        with patch.object(oidc_mod.urllib.request, 'urlopen', side_effect=err):
            with self.assertLogs('apps.users.oidc', level='ERROR') as logs:
                with self.assertRaises(oidc_mod.OidcError) as ctx:
                    oidc_mod.get_discovery()
        self.assertIn('CERTIFICATE_VERIFY_FAILED', str(ctx.exception))
        self.assertIn('证书校验失败', ''.join(logs.output))


class UserMapMissingFallbackTests(SimpleTestCase):
    """UserMap 缺失 → 回落 preferred_username 自动建档。

    风险: AD 别名/工号与本地用户名不一致时, 会生成重复的低权限账号
    (本用例锁定策略, 上线前必须用 91_usermap_integrity_checks.sql 核对覆盖)。
    """

    def test_fallback_auto_create_uses_preferred_username(self):
        claims = {'preferred_username': 'ligu', 'groups': ['app-bol'], 'email': 'a@b.c', 'name': '李'}
        saved = {}

        def fake_save(obj):
            saved.update(obj.__dict__)

        with patch('apps.users.oidc_views.connections') as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = None
            with patch('apps.users.oidc_views.Employee.objects.filter') as flt:
                flt.return_value.first.return_value = None
                with patch('apps.users.oidc_views.Employee.save', fake_save):
                    with override_settings(OIDC_REQUIRED_GROUP='app-bol', OIDC_AUTO_CREATE_USER=True):
                        resolve_or_create('ligu', ['app-bol'], claims)
        self.assertEqual(saved['username'], 'ligu')
        self.assertEqual(saved['role'], 'VIEWER')

    def test_auto_create_disabled_denies(self):
        with patch('apps.users.oidc_views.connections') as conns:
            conns.__getitem__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = None
            with patch('apps.users.oidc_views.Employee.objects.filter') as flt:
                flt.return_value.first.return_value = None
                with override_settings(OIDC_REQUIRED_GROUP='app-bol', OIDC_AUTO_CREATE_USER=False):
                    with self.assertRaises(PermissionDenied):
                        resolve_or_create('ghost', ['app-bol'], {'groups': ['app-bol']})
