"""AUTH_MODE=token: the bearer token decides who and as what; no token → 401 (fail closed)."""

import pytest
from fastapi.testclient import TestClient

from app.auth.services.token_service import TokenService
from config.settings import settings
from main import app
from tests.fixtures.slice import SLUG, pr_open, to_task


@pytest.fixture
def token_mode(monkeypatch):
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "token")


def bearer(token: str, **extra) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}", **extra})


def test_no_token_is_401_on_reads_writes_and_mcp(api, token_mode):
    anon = TestClient(app)
    assert anon.get("/api/initiatives").status_code == 401
    assert anon.post("/api/initiatives/1/records", json={"ops": []}).status_code == 401
    # X-Actor headers mean nothing in token mode
    spoof = TestClient(app, headers={"X-Actor": "priya", "X-Actor-Kind": "human"})
    r = spoof.get("/api/inbox")
    assert r.status_code == 401 and r.json()["error_code"] == "AUTH_REQUIRED"
    assert bearer("srs_nope").get("/api/initiatives").json()["error_code"] == "BAD_TOKEN"
    assert anon.post("/mcp", json={}).status_code == 401
    assert anon.get("/health").status_code == 200


def test_the_token_not_the_header_decides_the_kind(api, db_session, monkeypatch):
    to_task(api)  # the fixture state, built through the header-mode driver
    pr_open(api)
    iid = api.id(SLUG)
    tokens = TokenService(db_session)
    agent_token, _ = tokens.mint("runner-sdk", "agent", label="runner")
    human_token, _ = tokens.mint("priya", "human")
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "token")
    # an agent token that claims to be human is still an agent
    r = bearer(agent_token, **{"X-Actor": "priya", "X-Actor-Kind": "human"}).post(f"/api/initiatives/{iid}/approvals", json={"target": "T-1", "role": "engg"})
    assert r.status_code == 403 and r.json()["error_code"] == "HUMAN_ONLY"
    # the human token approves as priya, whatever X-Actor says
    r = bearer(human_token, **{"X-Actor": "mallory"}).post(f"/api/initiatives/{iid}/approvals", json={"target": "T-1", "role": "engg"})
    assert r.status_code == 201, r.text
    assert r.json()["results"][0]["ref"] == "APR-2"
    history = bearer(human_token).get(f"/api/initiatives/{iid}/records/APR-2/history").json()
    assert (history[0]["actor"], history[0]["actor_kind"]) == ("priya", "human")


def test_revoked_and_expired_tokens_fail(api, db_session, token_mode):
    from datetime import timedelta

    from app.core.utils.time import utcnow

    tokens = TokenService(db_session)
    live, row = tokens.mint("ci", "agent", roles=["ci"])
    assert bearer(live).get("/api/initiatives").status_code == 200
    tokens.revoke(row.id)
    assert bearer(live).get("/api/initiatives").status_code == 401
    old, _ = tokens.mint("ci", "agent", expires_at=utcnow() - timedelta(minutes=1))
    assert bearer(old).get("/api/initiatives").status_code == 401


def test_system_can_never_be_minted(db_session):
    from app.exceptions import ValidationException

    with pytest.raises(ValidationException):
        TokenService(db_session).mint("srs", "system")


def test_header_mode_is_refused_outside_local(monkeypatch):
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "header")
    with pytest.raises(RuntimeError, match="local/testing"):
        settings.auth.mode("production")
    monkeypatch.setattr(settings.auth, "AUTH_MODE", "")
    assert settings.auth.mode("production") == "token"
    assert settings.auth.mode("local") == "header"
