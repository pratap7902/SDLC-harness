"""actor: human — agents ask, humans answer."""

from tests.fixtures.slice import SLUG, draft_batch, to_task


def test_agent_writing_a_gap_answer_is_refused_and_a_human_may(api):
    api.start()
    api.write(SLUG, draft_batch())
    errors = api.rejected(SLUG, [{"ref": "G-1", "fields": {"answer": "yes"}}])
    assert errors == ["answer: human-only (agents ask, humans answer) — raise a gap, or ask in the web UI"]
    api.write(SLUG, [{"ref": "G-1", "fields": {"answer": "yes", "answered_by": "maya"}}], who=api.as_("maya"))
    assert api.record(SLUG, "G-1")["status"] == "ANSWERED"


def test_human_endpoints_return_403_to_agents(api):
    api.start()
    api.write(SLUG, draft_batch())
    agent = api.agent()
    for path, body in [
        (f"/api/initiatives/{SLUG}/gaps/G-1/answer", {"answer": "yes"}),
        (f"/api/initiatives/{SLUG}/decisions/D-1/rule", {"verdict": "v", "rationale": "r"}),
        (f"/api/initiatives/{SLUG}/approvals", {"target": "draft", "role": "dri"}),
        (f"/api/initiatives/{SLUG}/criteria/AC-1/sign", {"at_sha": "x"}),
        (f"/api/initiatives/{SLUG}/criteria/AC-1/retire", {"because": "x"}),
        (f"/api/initiatives/{SLUG}/snapshot", {"requirement": "x"}),
    ]:
        r = agent.post(path, json=body)
        assert r.status_code == 403, path
        assert r.json()["error_code"] == "HUMAN_ONLY"


def test_must_and_escalated_verdicts_are_human_only(api):
    api.start()
    must = {"type": "decision", "title": "PII", "fields": {"question": "Store emails?", "domain": "product", "level": "MUST", "verdict": "no"}}
    assert api.rejected(SLUG, [must])[0].startswith("verdict: human-only")
    esc = {"type": "decision", "title": "x", "fields": {"question": "q", "domain": "engg", "level": "SHOULD", "escalated": "yes", "verdict": "v"}}
    assert api.rejected(SLUG, [esc])[0].startswith("verdict: human-only")
    del must["fields"]["verdict"]
    api.write(SLUG, [must])
    assert [x["ref"] for x in api.get("/api/inbox/maya")["items"]] == ["D-1"]
    api.ok(api.as_("maya").post(f"/api/initiatives/{SLUG}/decisions/D-1/rule", json={"verdict": "No emails in events", "rationale": "GDPR"}))
    d1 = api.record(SLUG, "D-1")
    assert d1["status"] == "DECIDED" and d1["fields"]["decided_by"] == "maya"
    assert d1["stamps"]["verdict"]["kind"] == "human"
    r = api.as_("maya").post(f"/api/initiatives/{SLUG}/decisions/D-1/rule", json={"verdict": "x", "rationale": "y"})
    assert r.status_code == 422 and "ADRs are superseded" in r.json()["detail"]


def test_approvals_and_baselines_cannot_be_written_by_agents(api):
    api.start()
    errors = api.rejected(SLUG, [{"type": "approval", "fields": {"target": ["draft"], "role": "dri"}}])
    assert any(e.startswith("target: human-only") for e in errors)
    errors = api.rejected(SLUG, [{"type": "baseline", "fields": {"label": "x"}}])
    assert "type: baselines are written by the service when the DRI approves the draft" in errors


def test_the_approver_must_hold_the_role_and_the_gate_must_be_ready(api):
    to_task(api)
    r = api.approve(SLUG, "T-1", "engg", "chandra", expect=422)
    assert "chandra is not the engg of order-events (the engg is priya)" in r["detail"]
    r = api.approve(SLUG, "T-1", "engg", "priya", expect=422)
    assert r["detail"].startswith("GATE_PR (T-1) is not ready: pr_state_in (T-1)")
    r = api.approve(SLUG, "T-1", "dri", "chandra", expect=422)
    assert "a dri approves a draft, not a task" in r["detail"]


def test_mcp_callers_are_always_agents(api, db_session):
    from types import SimpleNamespace

    from app.mcp import server

    ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"x-actor": "chandra", "x-actor-kind": "human"})))
    actor = server._actor(ctx, "draft-skill")
    assert (actor.kind, actor.name) == ("agent", "chandra/draft-skill")
