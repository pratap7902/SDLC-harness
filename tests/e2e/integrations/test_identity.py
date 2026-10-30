"""One person, many front doors: a Cloudflare Access email and a bearer token both resolve
to the same canonical person."""

import time

import pytest
from fastapi.testclient import TestClient

from app.auth.services import cloudflare_access
from app.auth.services.token_service import TokenService
from app.people.services.people_service import PeopleService
from config.settings import settings
from main import app
from tests.fixtures.mock_http import install
from tests.fixtures.rsa import jwk, sign

TEAM = "acme.cloudflareaccess.com"


@pytest.fixture
def access(monkeypatch, db_session):
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "token")
    monkeypatch.setattr(settings.auth, "CF_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setattr(settings.auth, "CF_ACCESS_AUD", "aud-tag")
    monkeypatch.setattr(cloudflare_access, "_caches", {})
    install(monkeypatch).on("GET", rf"https://{TEAM}/cdn-cgi/access/certs", {"keys": [jwk("cf1")]})
    PeopleService(db_session).create("priya", "Priya", "priya@acme.dev")
    db_session.commit()


def assertion(email="priya@acme.dev", **over):
    claims = {"iss": f"https://{TEAM}", "aud": ["aud-tag"], "email": email, "exp": time.time() + 300, **over}
    return {"Cf-Access-Jwt-Assertion": sign(claims, kid="cf1")}


def test_a_verified_access_email_is_the_person(client, access):
    r = TestClient(app, headers=assertion()).get("/api/inbox")
    assert r.status_code == 200 and r.json()["person"] == "priya"


def test_access_failures(client, access):
    assert TestClient(app, headers=assertion("stranger@acme.dev")).get("/api/inbox").json()["error_code"] == "NOT_IN_DIRECTORY"
    assert TestClient(app, headers=assertion(aud=["other"])).get("/api/inbox").status_code == 401
    assert TestClient(app, headers={"Cf-Access-Jwt-Assertion": sign({"aud": ["aud-tag"], "email": "priya@acme.dev", "iss": f"https://{TEAM}"}, kid="cf1", seed=9)}).get("/api/inbox").status_code == 401
    # the plain email header is never trusted
    assert TestClient(app, headers={"Cf-Access-Authenticated-User-Email": "priya@acme.dev"}).get("/api/inbox").status_code == 401


def test_a_human_token_minted_by_email_is_the_same_person(client, access, db_session):
    token, row = TokenService(db_session).mint("PRIYA@acme.dev", "human")
    assert row.principal == "priya"
    via_token = TestClient(app, headers={"Authorization": f"Bearer {token}"}).get("/api/inbox").json()
    via_access = TestClient(app, headers=assertion()).get("/api/inbox").json()
    assert via_token["person"] == via_access["person"] == "priya"
    from app.exceptions import ValidationException

    with pytest.raises(ValidationException):
        TokenService(db_session).mint("nobody@acme.dev", "human")
