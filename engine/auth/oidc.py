# engine/auth/oidc.py
"""OIDC 的一方 —— 发现、换 token、看 id_token 里的 claims。

只做标准里最小的一段:授权码 + PKCE。不做隐式流,不做随意的 userinfo 扩展——
provider 各家花样很多,能用 discovery 的地方就用 discovery,不能用的地方不猜。

`id_token` 取 claims 用的是**直接解析**而不是验签,这是有意的取舍:

- 这个 token 是浏览器从我们的后台换回来的,走的是我们自己与 provider 之间的
  TLS 直连,攻击者没有插手的余地。
- 真要验签就得引 JOSE 依赖、拉 JWKS、处理各种算法。

一句话:链路可信,就不重复验一遍。要接"前端直接递 id_token 进来"的用法,
这条就站不住了 —— 那种场景没有实现,也不要加,除非同时把验签补上。
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from engine.shared.config import config

logger = logging.getLogger(__name__)


class OidcError(RuntimeError):
    """跟身份提供方打交道失败。message 里不带 token。"""


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    redirect_uri: str

    @classmethod
    def from_settings(cls, redirect_uri: str) -> "OidcConfig":
        s = config.settings
        if not (s.oidc_issuer and s.oidc_client_id and s.oidc_client_secret):
            raise OidcError("没配 OIDC(OIDC_ISSUER / OIDC_CLIENT_ID / OIDC_CLIENT_SECRET)")
        return cls(
            issuer=s.oidc_issuer.rstrip("/"),
            client_id=s.oidc_client_id,
            client_secret=s.oidc_client_secret,
            scopes=s.oidc_scopes or "openid email profile",
            redirect_uri=redirect_uri,
        )


_DISCOVERY: dict[str, dict] = {}


def discovery(issuer: str) -> dict:
    """一次进程内缓存:发现文档几乎是静态的,每次登录都拉一遍没必要。"""
    if issuer in _DISCOVERY:
        return _DISCOVERY[issuer]
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - 地址由运维配
            doc = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError) as exc:
        raise OidcError(f"拉不到 {issuer} 的发现文档:{exc}") from exc
    if "authorization_endpoint" not in doc or "token_endpoint" not in doc:
        raise OidcError(f"{issuer} 的发现文档缺 authorization/token 端点")
    _DISCOVERY[issuer] = doc
    return doc


def authorize_url(cfg: OidcConfig, *, state: str, nonce: str, code_challenge: str) -> str:
    doc = discovery(cfg.issuer)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{doc['authorization_endpoint']}?{query}"


def _decode_claims(id_token: str) -> dict:
    parts = (id_token or "").split(".")
    if len(parts) < 2:
        raise OidcError("id_token 形状不对")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OidcError("id_token 解不开") from exc


def exchange_code(cfg: OidcConfig, *, code: str, code_verifier: str) -> dict:
    """授权码换 token,再取 claims。"""
    doc = discovery(cfg.issuer)
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        doc["token_endpoint"],
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise OidcError(f"换 token 失败:{exc.code}") from exc
    except (urllib.error.URLError, ValueError) as exc:
        raise OidcError(f"换 token 失败:{exc}") from exc

    claims = _decode_claims(payload.get("id_token", ""))
    if not claims.get("sub"):
        raise OidcError("id_token 里没有 sub,这个提供方不符合 OIDC")
    claims.setdefault("email", payload.get("email", ""))
    return claims


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge)。S256,标准里唯一该用的那一种。"""
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


__all__ = [
    "OidcConfig",
    "OidcError",
    "authorize_url",
    "discovery",
    "exchange_code",
    "pkce_pair",
]
