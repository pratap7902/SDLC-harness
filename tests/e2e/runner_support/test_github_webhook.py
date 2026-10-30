"""POST /hooks/github: HMAC verification, PR → task pr_state/pr_sha, stale approvals."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from main import app
from tests.fixtures.slice import SLUG, to_task

SECRET = "test-webhook-secret"


@pytest.fixture
def hook(api, monkeypatch):
    monkeypatch.setattr(settings.github, "GITHUB_WEBHOOK_SECRET", SECRET)
    client = TestClient(app)  # no X-Actor: GitHub authenticates with the signature only

    def send(event, payload, delivery="d-1", secret=SECRET, signature=None):
        body = json.dumps(payload).encode()
        sig = signature if signature is not None else "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "Content-Type": "application/json"}
        if sig:
            headers["X-Hub-Signature-256"] = sig
        return client.post("/hooks/github", content=body, headers=headers)

    return send


def pr_payload(api, action="opened", sha="a" * 40, branch=None, merged=False, draft=False, body=""):
    return {
        "action": action,
        "pull_request": {
            "number": 7,
            "html_url": "https://github.com/example/orders/pull/7",
            "draft": draft,
            "merged": merged,
            "body": body,
            "head": {"ref": branch or f"harness/{api.id(SLUG)}-T-1", "sha": sha},
        },
    }


def test_signature_is_required_and_checked(api, hook):
    to_task(api)
    assert hook("pull_request", pr_payload(api), signature="").status_code == 401
    assert hook("pull_request", pr_payload(api), secret="wrong").status_code == 401
    assert hook("pull_request", pr_payload(api), signature="sha256=deadbeef").status_code == 401
    assert api.record(SLUG, "T-1")["fields"].get("pr_state") is None


def test_unconfigured_secret_refuses_everything(api, monkeypatch):
    monkeypatch.setattr(settings.github, "GITHUB_WEBHOOK_SECRET", "")
    r = TestClient(app).post("/hooks/github", content=b"{}", headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=x"})
    assert r.status_code == 503


def test_pr_opened_then_push_makes_the_approval_stale(api, hook):
    to_task(api)
    out = hook("pull_request", pr_payload(api, sha="a" * 40)).json()
    assert out["status"] == "updated" and out["task"] == "T-1"
    t = api.record(SLUG, "T-1")
    assert t["fields"]["pr_state"] == "open" and t["fields"]["pr_sha"] == "a" * 40
    assert t["fields"]["pr_url"].endswith("/pull/7")
    history = api.get(f"{api.base(SLUG)}/records/T-1/history")
    assert any(h["actor"] == "github/webhook" and h["actor_kind"] == "system" for h in history)

    # tests at that sha + engg approval → GATE_PR passes
    api.write(SLUG, [{"type": "test_run", "fields": {"summary": "suite", "level": "integration", "result": "GREEN", "at_sha": "a" * 40, "run_url": "https://ci.example.com/1", "run_on": "2026-10-31T15:00", "task": ["T-1"], "covers": [{"ac": a, "result": "GREEN"} for a in ("AC-1", "AC-2", "AC-3")]}}])
    api.approve(SLUG, "T-1", "engg", "priya")
    gate = api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]
    assert gate["status"] == "PASSED", gate

    # a new push: approval goes STALE without anyone touching it
    out = hook("push", {"ref": f"refs/heads/harness/{api.id(SLUG)}-T-1", "after": "b" * 40}, delivery="d-2").json()
    assert out["status"] == "updated"
    assert api.record(SLUG, "T-1")["fields"]["pr_sha"] == "b" * 40
    assert api.record(SLUG, "APR-2")["status"] == "STALE"
    assert api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]["status"] == "BLOCKED"


def test_replayed_delivery_is_idempotent_and_merge_sets_merged(api, hook):
    to_task(api)
    hook("pull_request", pr_payload(api))
    assert hook("pull_request", pr_payload(api)).json()["status"] == "unchanged"
    out = hook("pull_request", pr_payload(api, action="closed", merged=True), delivery="d-9").json()
    assert out["status"] == "updated" and api.record(SLUG, "T-1")["fields"]["pr_state"] == "merged"


def test_marker_and_draft_and_unknown(api, hook):
    to_task(api)
    out = hook("pull_request", pr_payload(api, branch="feature/x", draft=True, body=f"srs-task: {api.id(SLUG)}/T-1")).json()
    assert out["status"] == "updated" and api.record(SLUG, "T-1")["fields"]["pr_state"] == "draft"
    other = pr_payload(api, branch="feature/y")
    other["pull_request"]["html_url"] = "https://github.com/example/orders/pull/8"
    assert hook("pull_request", other, delivery="d-3").json()["status"] == "ignored"
    assert hook("ping", {"zen": "hi"}).json()["status"] == "ignored"
    assert hook("issues", {}).json()["status"] == "ignored"
    # push to a non-harness branch, or before any PR is recorded
    assert hook("push", {"ref": "refs/heads/main", "after": "c" * 40}).json()["status"] == "ignored"


def test_a_leased_task_still_takes_githubs_truth(api, hook):
    """Leases serialise agents only (the write path checks them for kind agent): the
    integration actor records GitHub's PR state even while a runner holds the task."""
    to_task(api)
    key = f"task:{api.id(SLUG)}:T-1"
    api.ok(api.agent().post("/api/leases/claim", json={"item_key": key}))
    out = hook("pull_request", pr_payload(api)).json()
    assert out["status"] == "updated"
    assert api.record(SLUG, "T-1")["fields"]["pr_state"] == "open"


def test_system_actor_cannot_forge_human_fields(api):
    """The integration actor goes through the same write path: actor:human fields refuse it."""
    from app.core.database import get_primary_db
    from app.github.services.webhook_service import GITHUB
    from app.initiatives.services.record_service import RecordService, parse_op

    to_task(api)
    db = app.dependency_overrides[get_primary_db]()
    records = RecordService(db)
    result = records.write(api.id(SLUG), [parse_op({"ref": "G-1", "fields": {"answer": "forged"}})], GITHUB, "forge-1")
    assert not result.ok and any("human" in e.lower() for r in result.results for e in r.errors)
    result = records.write(api.id(SLUG), [parse_op({"type": "approval", "fields": {"target": ["T-1"], "role": "engg"}})], GITHUB, "forge-2")
    assert not result.ok
