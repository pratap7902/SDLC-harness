import time

import pytest

from app.core.utils.jwt_rs256 import JwksCache, JwtError, verify
from tests.fixtures.rsa import jwk, sign


def cache(*keys):
    return JwksCache("https://issuer/certs", fetch=lambda _: {"keys": list(keys)})


def test_a_good_token_verifies():
    claims = {"iss": "https://i", "aud": ["app"], "email": "priya@acme.dev", "exp": time.time() + 60}
    assert verify(sign(claims), cache(jwk()), audience=["app"], issuer=["https://i"])["email"] == "priya@acme.dev"


@pytest.mark.parametrize(
    "token, why",
    [
        (lambda: sign({"aud": "app", "exp": time.time() + 60}, seed=8), "bad signature"),
        (lambda: sign({"aud": "other", "exp": time.time() + 60}), "audience"),
        (lambda: sign({"aud": "app", "exp": time.time() - 3600}), "expired"),
        (lambda: sign({"aud": "app"}, alg="HS256"), "RS256 only"),
        (lambda: sign({"aud": "app"}, kid="nope"), "no RSA key"),
        (lambda: "a.b", "malformed"),
    ],
)
def test_bad_tokens_are_refused(token, why):
    with pytest.raises(JwtError, match=why):
        verify(token(), cache(jwk()), audience=["app"])


def test_a_tampered_body_fails():
    good = sign({"aud": "app", "email": "a@x"})
    head, _, sig = good.split(".")
    forged = sign({"aud": "app", "email": "boss@x"}).split(".")[1]
    with pytest.raises(JwtError, match="bad signature"):
        verify(f"{head}.{forged}.{sig}", cache(jwk()), audience=["app"])
