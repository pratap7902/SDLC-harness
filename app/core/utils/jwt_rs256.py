"""Verify RS256 JWTs against a JWKS, in pure Python (RSASSA-PKCS1-v1_5 with SHA-256 is a
modular exponentiation and a byte comparison). Used for Cloudflare Access assertions and
Bot Framework (Teams) bearer tokens. Keys come from the issuer's JWKS URL, cached.

Only RS256 is accepted; `alg: none` / HS* are refused. exp / nbf are checked with a small
leeway; iss and aud are checked when given."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.utils import http

LEEWAY_S = 120
JWKS_TTL_S = 3600
# DER prefix of DigestInfo for SHA-256 (RFC 8017 §9.2 note 1)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class JwtError(Exception):
    pass


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int(value: str) -> int:
    return int.from_bytes(b64url_decode(value), "big")


def rsa_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(message).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def _get_json(url: str) -> Dict[str, Any]:
    with http.client() as c:
        return c.get(url).raise_for_status().json()


class JwksCache:
    """Fetches and caches a JWKS document. `fetch` is injectable for tests."""

    def __init__(self, url: str, fetch: Optional[Callable[[str], Dict[str, Any]]] = None):
        self.url = url
        self._fetch = fetch or _get_json
        self._keys: List[dict] = []
        self._at = 0.0

    def keys(self, refresh: bool = False) -> List[dict]:
        if refresh or not self._keys or time.time() - self._at > JWKS_TTL_S:
            doc = self._fetch(self.url)
            self._keys = list(doc.get("keys") or [])
            self._at = time.time()
        return self._keys

    def key(self, kid: Optional[str]) -> dict:
        for refresh in (False, True):  # a rotated key: refetch once
            for k in self.keys(refresh):
                if k.get("kty") == "RSA" and (kid is None or k.get("kid") == kid):
                    return k
        raise JwtError(f"no RSA key with kid {kid!r} in {self.url}")


def verify(
    token: str,
    jwks: JwksCache,
    audience: Optional[Iterable[str]] = None,
    issuer: Optional[Iterable[str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """The verified claims, or JwtError."""
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(b64url_decode(head_b64))
        claims = json.loads(b64url_decode(body_b64))
        signature = b64url_decode(sig_b64)
    except (ValueError, json.JSONDecodeError) as e:
        raise JwtError(f"malformed token: {e}") from e
    if header.get("alg") != "RS256":
        raise JwtError(f"alg {header.get('alg')!r} not accepted (RS256 only)")
    key = jwks.key(header.get("kid"))
    if not rsa_verify(_int(key["n"]), _int(key["e"]), f"{head_b64}.{body_b64}".encode(), signature):
        raise JwtError("bad signature")
    now = time.time() if now is None else now
    if "exp" in claims and now > float(claims["exp"]) + LEEWAY_S:
        raise JwtError("token expired")
    if "nbf" in claims and now + LEEWAY_S < float(claims["nbf"]):
        raise JwtError("token not yet valid")
    if audience is not None:
        aud = claims.get("aud")
        auds = set(aud if isinstance(aud, list) else [aud])
        if not auds & set(audience):
            raise JwtError(f"audience {aud!r} not accepted")
    if issuer is not None and claims.get("iss") not in set(issuer):
        raise JwtError(f"issuer {claims.get('iss')!r} not accepted")
    return claims
