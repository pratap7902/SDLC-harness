"""Regression tests for the trust-boundary bugs (B1–B9 of the 2026-10-29 assessment). Each
was a probe that demonstrated the hole on 2d926de; here each asserts the fixed behaviour."""

from app.core.utils.actor import Actor
from app.initiatives.services.record_service import RecordService, parse_op
from tests.fixtures.slice import SLUG, deviation_gap, draft_batch, pr_open, to_task


def errs(out):
    return [e for r in out.get("error_data", out).get("results", []) for e in r.get("errors", [])]


# ── B1: nobody outside the service writes a baseline, or acts as `system` ──────────


def test_b1_a_caller_cannot_claim_system(api):
    to_task(api)
    r = api.as_("anyone", "system").post(
        f"{api.base(SLUG)}/records",
        json={"ops": [{"type": "baseline", "fields": {"label": "forged", "approval": ["APR-1"], "draft_rev": "1"}}]},
    )
    assert r.status_code == 403 and r.json()["error_code"] == "KIND_NOT_ALLOWED"
    assert [b["ref"] for b in api.get(f"{api.base(SLUG)}/records", type="baseline")] == ["B-1"]


def test_b1_even_the_system_kind_cannot_write_a_baseline_through_write(api, db_session):
    to_task(api)
    service = RecordService(db_session)
    out = service.write(
        str(api.id(SLUG)),
        [parse_op({"type": "baseline", "fields": {"label": "forged", "approval": ["APR-1"], "draft_rev": "1"}})],
        Actor("srs", "system"),
    )
    assert not out.ok
    assert "type: baselines are written by the service when the DRI approves the draft" in out.results[0].errors


def test_b1_system_does_not_skip_because(api, db_session):
    """P4b: the `system` kind used to be exempt from post-baseline `because`."""
    to_task(api)
    out = RecordService(db_session).write(
        str(api.id(SLUG)), [parse_op({"ref": "AC-1", "fields": {"text": "Given anything, then pass"}})], Actor("srs", "system")
    )
    assert not out.ok and out.results[0].errors[0].startswith("because: spec change after baseline B-1")
    assert api.drift(SLUG)["status"] == "CLEAN"


def test_b1_mcp_never_takes_system_or_human_from_headers():
    from types import SimpleNamespace

    from app.mcp.server import _actor

    for kind in ("system", "human"):
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-actor": "x", "x-actor-kind": kind})))
        assert _actor(ctx, None).kind == "agent"


# ── B2 / B3: every explanation ends in a human act ────────────────────────────────


def test_b2_an_agent_cannot_explain_a_draft_rewrite_with_its_own_finding(api):
    to_task(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "lld should change", "severity": "nit", "target": ["draft"]}}])
    out = api.write(SLUG, [{"ref": "draft", "fields": {"lld": "Totally different design: a cron job."}, "because": ["F-1"]}], expect=422)
    assert any(e.startswith("because: F-1 does not explain a spec change") and "no human" in e for e in errs(out))
    assert api.drift(SLUG)["status"] == "CLEAN" and api.record(SLUG, "draft")["status"] == "APPROVED"


def test_b2_control_a_finding_explains_once_a_human_raised_or_resolved_it(api):
    to_task(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "lld should change", "severity": "nit", "target": ["draft"]}}])
    # the agent's own finding, acknowledged by a human, now carries a human act
    api.write(SLUG, [{"ref": "F-1", "fields": {"resolution": "acknowledged", "resolution_note": "agreed"}}], who=api.as_("priya"))
    api.write(SLUG, [{"ref": "draft", "fields": {"lld": "Relay polls every 500ms."}, "because": ["F-1"]}])
    # a finding a human raised explains on its own
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "AC-3 wording", "severity": "nit", "target": ["AC-3"]}}], who=api.as_("priya"))
    api.write(SLUG, [{"ref": "AC-3", "fields": {"text": "Two updates to one order share partition key order_id"}, "because": ["F-2"]}])
    d = api.drift(SLUG)
    assert d["status"] == "EXPLAINED" and all(e["explained"] for e in d["entries"])


def test_b3_an_agent_cannot_supersede_an_approved_decision_on_its_own_finding(api):
    to_task(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "envelope is wrong", "severity": "nit", "target": ["D-2"]}}])
    out = api.write(
        SLUG,
        [{"type": "decision", "title": "Avro", "fields": {"question": "Envelope?", "domain": "engg", "level": "SHOULD", "verdict": "Avro, no partition key", "rationale": "agent prefers", "decided_by": "agent", "decided_on": "2026-10-31", "supersedes": ["D-2"], "because": ["F-1"]}}],
        expect=422,
    )
    assert any(e.startswith("because: F-1 does not explain") for e in errs(out))
    assert api.record(SLUG, "D-2")["status"] == "DECIDED"
    assert api.drift(SLUG, task="T-1")["status"] == "CLEAN"


def test_b3_control_an_agent_decision_grounded_in_a_human_answer_explains(api):
    to_task(api)
    api.write(SLUG, [deviation_gap()])
    api.answer(SLUG, "G-2", choice="cdc", person="priya")
    # agent decision grounded on the human answer → ok; a second decision grounded on it → ok
    api.write(SLUG, [{"type": "decision", "title": "CDC", "fields": {"question": "q", "domain": "engg", "level": "SHOULD", "verdict": "CDC", "rationale": "G-2", "decided_by": "a", "decided_on": "2026-10-31", "supersedes": ["D-1"], "because": ["G-2"]}}])
    d = api.drift(SLUG)
    assert d["status"] == "EXPLAINED"


# ── B4: the human rule cannot be stepped around ────────────────────────────────────


def test_b4_an_agent_cannot_downgrade_a_must_decision_then_rule_it(api):
    api.start()
    api.write(SLUG, draft_batch())
    out = api.write(SLUG, [{"type": "decision", "title": "PII retention", "fields": {"question": "Retain PII?", "domain": "product", "level": "MUST", "escalated": "yes"}}])
    ref = out["results"][0]["ref"]
    errors = api.rejected(SLUG, [{"ref": ref, "fields": {"level": "SHOULD", "escalated": "no"}}])
    assert any(e.startswith("level: human-only") for e in errors) and any(e.startswith("escalated: human-only") for e in errors)
    errors = api.rejected(SLUG, [{"ref": ref, "fields": {"escalated": "no"}}])
    assert errors[0].startswith("escalated: human-only")
    # an agent may still ratchet UP (SHOULD → MUST); only a human may step down
    api.write(SLUG, [{"ref": "D-2", "fields": {"level": "MUST"}}])
    assert api.rejected(SLUG, [{"ref": "D-2", "fields": {"level": "SHOULD"}}])[0].startswith("level: human-only")
    api.write(SLUG, [{"ref": ref, "fields": {"level": "SHOULD", "escalated": "no"}}], who=api.as_("maya"))
    assert api.record(SLUG, ref)["fields"]["level"] == "SHOULD"


# ── B5: test evidence is bound to the commit ───────────────────────────────────────


def guard(api, sha, env="production"):
    return api.get("/api/deploy-guard", initiative_id=api.id(SLUG), task="T-1", sha=sha, environment=env)


def test_b5_runs_at_an_older_sha_do_not_count(api):
    to_task(api)
    pr_open(api, sha="old111")
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_sha": "new222"}}])
    r = api.approve(SLUG, "T-1", "engg", "priya", at_sha="new222", expect=422)
    assert "every_covered_ac_has_a_test" in r["detail"]
    out = guard(api, "new222")
    assert out["decision"] == "NO-GO"
    failing = {c["name"]: c["detail"] for c in out["checks"] if not c["passed"]}
    assert "every_ac_green" in failing["GATE_VALIDATED"]
    # green at the new head → approvable → GO
    pr_open(api, sha="new222")
    api.approve(SLUG, "T-1", "engg", "priya", at_sha="new222")
    assert guard(api, "new222")["decision"] == "GO"


# ── B6: a human's (or a serious) finding is closed by a human ──────────────────────


def test_b6_an_agent_cannot_clear_a_human_blocker(api):
    to_task(api)
    pr_open(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "SQL injection in relay", "severity": "blocker", "target": ["T-1"], "at_sha": "abc123"}}], who=api.as_("priya"))
    errors = api.rejected(SLUG, [{"ref": "F-1", "fields": {"resolution": "acknowledged", "resolution_note": "fine"}}])
    assert errors[0].startswith("resolution: human-only")
    # nor step around it by downgrading the severity first
    assert any(e.startswith("severity: human-only") for e in api.rejected(SLUG, [{"ref": "F-1", "fields": {"severity": "nit"}}]))
    g = api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]
    assert "no_blocker_finding_open_at_sha" in g["failing_rules"]


def test_b6_an_agent_may_close_its_own_minor_finding(api):
    to_task(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "typo", "severity": "nit", "target": ["T-1"]}}])
    api.write(SLUG, [{"ref": "F-1", "fields": {"resolution": "fixed"}}])
    assert api.record(SLUG, "F-1")["status"] == "FIXED"
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "auth", "severity": "major", "target": ["T-1"]}}])
    assert api.rejected(SLUG, [{"ref": "F-2", "fields": {"resolution": "fixed"}}])[0].startswith("resolution: human-only")


# ── B7: review items are upheld by humans ──────────────────────────────────────────


def _queued(api):
    to_task(api)
    api.write(SLUG, [deviation_gap()])
    api.answer(SLUG, "G-2", choice="cdc", person="priya")
    items = api.get(f"{api.base(SLUG)}/reviews")
    assert items
    return items


def test_b7_an_agent_cannot_uphold_or_dismiss_a_review_item(api):
    items = _queued(api)
    for resolution in ("upheld", "dismissed"):
        r = api.agent().post(f"{api.base(SLUG)}/reviews/{items[0]['id']}/resolve", json={"resolution": resolution, "note": "agent says fine"})
        assert r.status_code == 403 and r.json()["error_code"] == "HUMAN_ONLY"
    r = api.as_("priya").post(f"{api.base(SLUG)}/reviews/{items[0]['id']}/resolve", json={"resolution": "upheld", "note": "holds"})
    assert r.status_code == 200 and r.json()["status"] == "upheld"


def test_b7_an_agent_review_leaves_the_item_open_for_a_human(api):
    items = _queued(api)
    target = items[0]["target"]
    out = api.write(SLUG, [{"ref": target, "reviewed": True, "note": "still holds"}])
    assert out["results"][0]["action"] == "reviewed"
    still = [i for i in api.get(f"{api.base(SLUG)}/reviews") if i["target"] == target]
    assert still and all(i["status"] == "open" and i["judged_by"] == "agent" for i in still)
    assert "still holds" in still[0]["note"]
    api.write(SLUG, [{"ref": target, "reviewed": True, "note": "agree"}], who=api.as_("priya"))
    assert not [i for i in api.get(f"{api.base(SLUG)}/reviews") if i["target"] == target]


def test_b7_mcp_cannot_uphold(api):
    import pytest

    from app.mcp import server

    items = _queued(api)
    ctx = type("C", (), {"request_context": type("R", (), {"request": type("Q", (), {"headers": {"x-actor": "runner-sdk"}})()})()})()
    with pytest.raises(ValueError, match="human"):
        server.resolve_review_item(api.id(SLUG), items[0]["id"], "upheld", "fine", ctx)


# ── B8: batch_id idempotency is scoped ─────────────────────────────────────────────


def test_b8_a_batch_id_reused_in_another_initiative_is_refused(api):
    api.start()
    api.start(slug="other-feature", title="Other")
    op = [{"type": "gap", "fields": {"question": "q?", "kind": "unknown", "domain": "engg", "asked_by": "a", "why_now": "w", "context": "c"}}]
    api.write(SLUG, op, batch_id="same-1")
    out = api.write("other-feature", op, batch_id="same-1", expect=409)
    assert out["error_code"] == "BATCH_ID_REUSED"
    assert api.get(f"{api.base('other-feature')}/records", type="gap") == []
    # and by another actor in the same initiative
    out = api.write(SLUG, op, who=api.as_("runner-b", "agent"), batch_id="same-1", expect=409)
    assert out["error_code"] == "BATCH_ID_REUSED"
    # the same caller replaying is still idempotent
    assert api.write(SLUG, op, batch_id="same-1")["replayed"] is True


# ── B9: a lease guards writes ──────────────────────────────────────────────────────


def test_b9_another_agent_cannot_write_a_leased_task(api):
    to_task(api)
    key = f"task:{api.id(SLUG)}:T-1"
    assert api.as_("runner-a", "agent").post("/api/leases/claim", json={"item_key": key}).status_code == 200
    r = api.as_("runner-b", "agent").post(f"{api.base(SLUG)}/records", json={"ops": [{"ref": "T-1", "fields": {"pr_state": "draft"}}]})
    assert r.status_code == 422
    assert any("leased by runner-a" in e for e in errs(r.json()))
    ok = api.as_("runner-a", "agent").post(f"{api.base(SLUG)}/records", json={"ops": [{"ref": "T-1", "fields": {"pr_state": "draft"}}], "agent": "implement-task"})
    assert ok.status_code == 200
    assert api.as_("priya").post(f"{api.base(SLUG)}/records", json={"ops": [{"ref": "T-1", "fields": {"rollback": "flag off"}}]}).status_code == 200


# ── identity: no caller is human by default ────────────────────────────────────────


def test_a_missing_kind_is_an_agent_not_a_human(api):
    to_task(api)
    r = api.as_("priya", "").post(f"{api.base(SLUG)}/approvals", json={"target": "T-1", "role": "engg"})
    assert r.status_code == 403 and r.json()["error_code"] == "HUMAN_ONLY"
