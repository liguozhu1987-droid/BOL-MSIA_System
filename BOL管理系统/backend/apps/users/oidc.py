# -*- coding: utf-8 -*-
"""OIDC (Keycloak) 接入核心模块 (Django 版)

与 MSIA Report 的 ``app/core/oidc.py`` 同构 (方案文档第 6 章),
差异仅在配置来源 (django.conf.settings) 与日志 (logging)。

设计约束 (方案文档第 5 章 / 12.4):
- HTTP 使用 stdlib urllib.request, 不引入 requests/authlib 等新依赖
- JWKS 验签使用 PyJWT 的 PyJWKClient (RS256, 需 cryptography)
- discovery 文档模块级缓存 (TTL 10min)
- state/nonce/PKCE verifier 内存存储 (TTL 10min, threading.Lock 保护)
- OTK 一次性码 (TTL 60s, 单次消费, threading.Lock 保护): OIDC 回调成功后
  前端凭 otk 换本地 AuthToken, 避免 token 出现在 URL 跳转链中被日志记录

安全点:
- state 防 CSRF, nonce 防重放, PKCE S256 防授权码截获
- 内存存储为单实例部署设计 (BOL 后端为单进程 waitress 部署)
"""
import base64
import hashlib
import json
import logging
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple

import jwt
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量
_HTTP_TIMEOUT = 15  # 秒
_DISCOVERY_TTL = 600  # discovery 缓存 10 分钟
_SESSION_TTL = 600  # state/nonce/verifier 存储 10 分钟
_OTK_TTL = 60  # 一次性码 60 秒

# discovery 缓存: {"doc": {...}, "expires_at": float}
_discovery_cache: Dict[str, Any] = {"doc": None, "expires_at": 0.0}
_discovery_lock = threading.Lock()

# OIDC 会话存储: state -> {"nonce": str, "code_verifier": str, "expires_at": float}
_oidc_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()

# OTK 一次性码存储: otk -> {"employee_id": int, "token": str, "expires_at": float}
_otk_store: Dict[str, Dict[str, Any]] = {}
_otk_lock = threading.Lock()


class OtkError(Exception):
    """OTK 无效/已消费/已过期"""


class OidcError(Exception):
    """OIDC 流程错误 (discovery/token 交换/验签失败等)"""


# ---------------------------------------------------------------- PKCE
def _b64url_no_pad(data: bytes) -> str:
    """base64url 编码并去除尾部 '=' (PKCE 规范)"""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def create_pkce_pair() -> Tuple[str, str]:
    """生成 PKCE (verifier, challenge) 对

    verifier: 48 字节随机数 (base64url, 约 64 字符)
    challenge: base64url(sha256(verifier)) 去 '='
    """
    verifier = _b64url_no_pad(secrets.token_bytes(48))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ---------------------------------------------------------------- discovery
def _http_get_json(url: str) -> Dict[str, Any]:
    """stdlib GET JSON (urllib)"""
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except ssl.SSLCertVerificationError as e:
        logger.error("OIDC HTTPS 证书校验失败 (%s): %s; 请将企业根 CA 装入运行进程信任库", url, e)
        raise OidcError(f"OIDC HTTPS 证书校验失败: {e}") from e


def _http_post_form(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    """stdlib POST application/x-www-form-urlencoded (urllib)"""
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except ssl.SSLCertVerificationError as e:
        logger.error("OIDC HTTPS 证书校验失败 (%s): %s; 请将企业根 CA 装入运行进程信任库", url, e)
        raise OidcError(f"OIDC HTTPS 证书校验失败: {e}") from e


def get_discovery() -> Dict[str, Any]:
    """获取 realm discovery 文档 (带 TTL 缓存)

    缓存 jwks_uri / authorization_endpoint / token_endpoint / userinfo_endpoint。
    缓存过期后重新拉取; 拉取失败时若有旧文档则降级返回旧文档并告警。
    """
    now = time.monotonic()
    with _discovery_lock:
        cached = _discovery_cache
        if cached["doc"] is not None and now < cached["expires_at"]:
            return cached["doc"]

    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    try:
        doc = _http_get_json(url)
    except Exception as e:
        # 降级: 网络闪断时优先可用性, 旧文档仍在则返回旧文档
        with _discovery_lock:
            if cached["doc"] is not None:
                logger.warning("OIDC discovery 拉取失败, 降级使用缓存文档: %s", e)
                return cached["doc"]
        raise OidcError(f"OIDC discovery 拉取失败: {e}") from e

    with _discovery_lock:
        _discovery_cache["doc"] = doc
        _discovery_cache["expires_at"] = time.monotonic() + _DISCOVERY_TTL
    return doc


# ---------------------------------------------------------------- 授权 URL / 令牌交换
def build_authorize_url(state: str, nonce: str, code_challenge: str) -> str:
    """构建 Keycloak 授权端点完整 URL (授权码 + PKCE S256)"""
    doc = get_discovery()
    params = {
        "response_type": "code",
        "scope": settings.OIDC_SCOPES,
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return doc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str, code_verifier: str) -> Dict[str, Any]:
    """用授权码交换 token (grant_type=authorization_code, 带 PKCE verifier)"""
    doc = get_discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "client_id": settings.OIDC_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    if settings.OIDC_CLIENT_SECRET:
        # confidential client: client_secret 走 POST body (Basic 亦可, 二者等价)
        data["client_secret"] = settings.OIDC_CLIENT_SECRET
    return _http_post_form(doc["token_endpoint"], data)


def verify_id_token(id_token: str, nonce: str) -> Dict[str, Any]:
    """校验 id_token 签名与声明, 返回 claims

    - 签名: PyJWKClient 按 kid 拉 JWKS 公钥验签 (RS256)
    - 校验: audience=client_id, issuer=realm issuer, exp/iat, nonce (leeway 60s)
    """
    doc = get_discovery()
    jwks_client = jwt.PyJWKClient(doc["jwks_uri"])
    signing_key = jwks_client.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.OIDC_CLIENT_ID,
        issuer=settings.OIDC_ISSUER,
        leeway=60,
        options={"verify_aud": True, "verify_iss": True},
    )
    token_nonce = claims.get("nonce")
    if not token_nonce or token_nonce != nonce:
        raise ValueError("id_token nonce 校验失败 (疑似重放)")
    return claims


# ---------------------------------------------------------------- state/nonce 会话存储
def store_oidc_session(state: str, nonce: str, code_verifier: str) -> None:
    """存储 OIDC 登录会话 (state -> nonce + PKCE verifier), TTL 10min"""
    with _sessions_lock:
        _purge_expired(_oidc_sessions)
        _oidc_sessions[state] = {
            "nonce": nonce,
            "code_verifier": code_verifier,
            "expires_at": time.monotonic() + _SESSION_TTL,
        }


def consume_oidc_session(state: str) -> Dict[str, Any]:
    """消费式取出 OIDC 会话 (一次性, 防重放)

    Raises:
        KeyError: state 不存在或已过期
    """
    with _sessions_lock:
        item = _oidc_sessions.pop(state, None)
        if item is None:
            raise KeyError("state 不存在或已被消费")
        if time.monotonic() > item["expires_at"]:
            raise KeyError("state 已过期")
        return item


# ---------------------------------------------------------------- OTK 一次性码
def create_otk(employee_id: int, token: str) -> str:
    """创建一次性码 (60s TTL, 单次消费)

    otk 载荷仅含 employee_id + 已签发的 AuthToken.key; 前端凭此换登录态。
    """
    otk = _b64url_no_pad(secrets.token_bytes(32))
    with _otk_lock:
        _purge_expired(_otk_store)
        _otk_store[otk] = {
            "employee_id": employee_id,
            "token": token,
            "expires_at": time.monotonic() + _OTK_TTL,
        }
    return otk


def consume_otk(otk: str) -> Dict[str, Any]:
    """消费一次性码, 返回 {"employee_id": int, "token": str}

    Raises:
        OtkError: otk 无效 / 已消费 / 已过期
    """
    with _otk_lock:
        item = _otk_store.pop(otk, None)
        if item is None:
            raise OtkError("otk 无效或已被消费")
        if time.monotonic() > item["expires_at"]:
            raise OtkError("otk 已过期")
        return item


# ---------------------------------------------------------------- 配置体检
def mask_secret(value) -> str:
    """脱敏 client_secret (日志可打印, 不泄漏明文)"""
    value = (value or "").strip()
    if not value:
        return "(空)"
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def validate_config() -> Dict[str, Any]:
    """OIDC 配置体检 (fail loud, 不 fail silent)

    检查项:
      - enabled=true 但 client_secret 为空
      - redirect_uri 仍含 127.0.0.1 / localhost 占位特征
      - issuer 与 redirect_uri 主机名不一致
      - issuer 不是 https
    每条问题都带配置键名与当前值 (secret 脱敏)。

    Returns:
        {"enabled": bool, "errors": [...], "warnings": [...], "info": [...]}
    """
    result: Dict[str, Any] = {
        "enabled": bool(settings.OIDC_ENABLED),
        "errors": [],
        "warnings": [],
        "info": [],
    }
    if not settings.OIDC_ENABLED:
        # 双轨期关闭状态: 只记一条 info, 不打扰
        result["info"].append("OIDC 未启用 (oidc.enabled=false), 跳过配置体检")
        return result

    issuer = (settings.OIDC_ISSUER or "").strip()
    redirect_uri = (settings.OIDC_REDIRECT_URI or "").strip()
    secret = settings.OIDC_CLIENT_SECRET or ""

    if not secret.strip():
        result["errors"].append(
            "oidc.client_secret 为空 (当前值: {}); confidential client 无法换取 token".format(
                mask_secret(secret))
        )

    issuer_parts = urllib.parse.urlsplit(issuer)
    redirect_parts = urllib.parse.urlsplit(redirect_uri)
    issuer_host = (issuer_parts.hostname or "").lower()
    redirect_host = (redirect_parts.hostname or "").lower()

    if redirect_host in ("127.0.0.1", "localhost") or "127.0.0.1" in redirect_uri:
        result["errors"].append(
            "oidc.redirect_uri 仍是本机占位地址 (当前值: {}); Keycloak 侧会拒绝该回跳".format(
                redirect_uri)
        )

    if issuer_host and redirect_host and issuer_host != redirect_host:
        result["errors"].append(
            "oidc.issuer 主机名 ({}) 与 oidc.redirect_uri 主机名 ({}) 不一致; "
            "浏览器会话需使用同一主机".format(issuer_host, redirect_host)
        )

    if issuer_parts.scheme.lower() != "https":
        result["errors"].append(
            "oidc.issuer 不是 https (当前值: {}); 生产 Keycloak 要求 https".format(issuer)
        )

    return result


def log_config_problems(result: Dict[str, Any]) -> None:
    """按严重级别输出体检结果 (ERROR 列键名与当前值, INFO 仅在关闭时一条)"""
    for item in result.get("errors", []):
        logger.error("OIDC 配置体检失败: %s", item)
    for item in result.get("warnings", []):
        logger.warning("OIDC 配置体检警告: %s", item)
    for item in result.get("info", []):
        logger.info("OIDC 配置体检: %s", item)


# ---------------------------------------------------------------- 内部工具
def _purge_expired(store: Dict[str, Dict[str, Any]]) -> None:
    """清理过期条目 (调用方须持有对应锁)"""
    now = time.monotonic()
    expired = [k for k, v in store.items() if now > v["expires_at"]]
    for k in expired:
        del store[k]
