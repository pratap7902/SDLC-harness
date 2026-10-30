"""A throwaway RSA key and JWT signer for tests (pure Python; no crypto dependency)."""

import hashlib
import json
import random
from functools import lru_cache

from app.core.utils.jwt_rs256 import SHA256_PREFIX, b64url_encode


def _probable_prime(bits: int, rng: random.Random) -> int:
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and _miller_rabin(n, rng):
            return n


def _miller_rabin(n: int, rng: random.Random, rounds: int = 16) -> bool:
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


@lru_cache(maxsize=4)
def keypair(seed: int = 7, bits: int = 1024):
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _probable_prime(bits // 2, rng), _probable_prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


def jwk(kid: str = "k1", seed: int = 7) -> dict:
    n, e, _ = keypair(seed)
    return {"kty": "RSA", "kid": kid, "alg": "RS256", "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": b64url_encode(e.to_bytes(3, "big"))}


def sign(claims: dict, kid: str = "k1", seed: int = 7, alg: str = "RS256") -> str:
    n, _, d = keypair(seed)
    k = (n.bit_length() + 7) // 8
    head = b64url_encode(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    body = b64url_encode(json.dumps(claims).encode())
    t = SHA256_PREFIX + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{head}.{body}.{b64url_encode(sig)}"
