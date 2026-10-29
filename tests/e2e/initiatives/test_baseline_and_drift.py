"""The vertical slice (plan §9), end to end over REST:

start a feature → agent writes a draft (2 decisions, 1 gap, 3 ACs) → a human answers the
gap in the inbox → the DRI approves the draft (baseline B-1) → agent plans 1 task → agent
hits a deviation and raises a gap → a human answers → agent supersedes D-1 and adds AC-4
with `because` → drift_report(T-1) shows the chain, 0 unexplained → engg approves at sha →
deploy_guard says GO; a later change moves the digest (NO-GO), and a cause that stops
explaining turns the drift UNEXPLAINED."""

from tests.fixtures.slice import SLUG, deviation_gap, draft_batch, supersede_batch, task_op


def gate(state, key):
    return next(g for g in state["gates"] if g["gate"] == key)


def test_vertical_slice(api):
    # ── intake ────────────────────────────────────────────────────────────
    started = api.start()
    assert started["phase"] == "DRAFT"
    assert started["initiative"]["spec_snapshot"]["work_item_url"].startswith("https://dev.azure.com/")
    assert {a["role"]: a["person"] for a in started["assignments"]} == {"dri": "chandra", "engg": "priya", "product": "maya", "qa": "sam"}

    # ── touchpoint 1: the draft ───────────────────────────────────────────
    out = api.write(SLUG, draft_batch())
    assert out["minted"] == {"#0": "D-1", "#1": "D-2", "#2": "G-1", "#3": "AC-1", "#4": "AC-2", "#5": "AC-3"}
    state = api.state(SLUG)
    g1 = gate(state, "GATE_DRAFT")
    assert g1["status"] == "BLOCKED"
    assert g1["failing_rules"] == ["no_open_gap_blocking_draft", "approval_by_role"]
    page = api.get(f"{api.base(SLUG)}/draft")
    assert page["can_approve"] is False and page["approval_blockers"][0]["failing"] == ["G-1"]

    # the gap lands in the product person's inbox; an agent cannot answer it
    inbox = api.inbox("maya")
    assert [(x["kind"], x["ref"]) for x in inbox["items"]] == [("gap", "G-1")]
    errors = api.rejected(SLUG, [{"ref": "G-1", "fields": {"answer": "yes", "answered_by": "runner"}}])
    assert any("answer: human-only" in e for e in errors)
    api.answer(SLUG, "G-1", choice="yes", person="maya")

    # the answer queues D-2 (blocked by G-1) for review, routed to the engg assignee
    reviews = api.get(f"{api.base(SLUG)}/reviews")
    assert [(r["target"], r["cause"], r["route_to"]) for r in reviews] == [("D-2", "G-1", "priya")]
    assert gate(api.state(SLUG), "GATE_DRAFT")["failing_rules"] == ["no_open_review_items_on_spec", "approval_by_role"]
    api.write(SLUG, [{"ref": "D-2", "fields": {"rationale": "Consumers parse CloudEvents; G-1: billing needs per-order ordering."}, "note": "per G-1"}])
    assert api.get(f"{api.base(SLUG)}/reviews") == []

    # only the DRI approves; an agent is refused outright
    assert api.agent().post(f"{api.base(SLUG)}/approvals", json={"target": "draft", "role": "dri"}).status_code == 403
    refused = api.approve(SLUG, "draft", "dri", "priya", expect=422)
    assert "priya is not the dri" in refused["detail"]
    approved = api.approve(SLUG, "draft", "dri", "chandra")
    assert approved["baseline"] == "B-1"

    state = api.state(SLUG)
    assert gate(state, "GATE_DRAFT")["status"] == "PASSED"
    assert state["phase"] == "PLAN"
    assert state["baseline"]["members"] == ["draft", "D-1", "D-2", "AC-1", "AC-2", "AC-3", "G-1"]
    assert api.record(SLUG, "AC-1")["status"] == "APPROVED"
    assert api.drift(SLUG)["status"] == "CLEAN"

    # ── plan + build ──────────────────────────────────────────────────────
    api.write(SLUG, [task_op()])
    assert api.state(SLUG)["phase"] == "BUILD"
    claimed = api.ok(api.agent().post("/api/leases/claim", json={"item_key": f"task:{api.id(SLUG)}:T-1"}))
    assert claimed["holder"] == "runner-sdk"
    assert api.record(SLUG, "T-1")["status"] == "IN_PROGRESS"

    # ── touchpoint 2: a deviation mid-build ───────────────────────────────
    out = api.write(SLUG, [deviation_gap()])
    assert out["minted"] == {"#0": "G-2"}
    assert api.record(SLUG, "T-1")["status"] == "BLOCKED"
    pending = api.drift(SLUG, task="T-1")
    assert pending["pending_gaps"][0]["ref"] == "G-2" and pending["summary"]["changes"] == 0

    # the agent cannot change the spec on its own: no because, or a because still OPEN
    no_because = supersede_batch()
    del no_because[0]["fields"]["because"]
    errors = api.rejected(SLUG, no_because)
    assert any("needs `because`" in e for e in errors)
    errors = api.rejected(SLUG, supersede_batch())
    assert any("G-2 is OPEN" in e for e in errors)
    # nor edit an ADR in place
    errors = api.rejected(SLUG, [{"ref": "D-1", "fields": {"verdict": "CDC"}, "because": ["G-2"]}])
    assert any("ADRs are superseded, never edited" in e for e in errors)

    assert [x["ref"] for x in api.inbox("priya")["items"]] == ["G-2"]
    api.answer(SLUG, "G-2", answer="Use CDC — the outbox adds a table we don't own.", choice="cdc", person="priya")
    out = api.write(SLUG, supersede_batch())
    assert out["minted"] == {"#0": "D-3", "#1": "AC-4"}
    assert api.record(SLUG, "D-1")["status"] == "SUPERSEDED"
    assert api.record(SLUG, "AC-4")["status"] == "ADDED_AFTER_BASELINE"
    assert api.get(f"{api.base(SLUG)}/reviews") == []  # D-1 superseded, T-1 revised

    # ── the drift report: the chain, 0 unexplained ────────────────────────
    report = api.drift(SLUG, task="T-1")
    assert report["status"] == "EXPLAINED"
    chain = [(e["kind"], e["ref"], e["actor_kind"], e["because"], e["explained"]) for e in report["entries"]]
    assert chain == [
        ("gap_answered", "G-2", "human", [], True),
        ("decision_superseded", "D-3", "agent", ["G-2"], True),
        ("ac_added", "AC-4", "agent", ["D-3"], True),
    ]
    assert report["summary"] == {"changes": 3, "explained": 3, "unexplained": 0, "pending_gaps": 0, "pending_decisions": 0, "other_changes": 0}
    assert report["spec_diff"]["decisions"]["superseded"] == [
        {"old": "D-1", "new": "D-3", "old_verdict": draft_batch()[0]["fields"]["verdict"], "new_verdict": "CDC via Debezium on the orders binlog"}
    ]
    assert [a["ref"] for a in report["spec_diff"]["criteria"]["added"]] == ["AC-4"]
    assert [d["ref"] for d in report["current_spec"]["decisions"]] == ["D-2", "D-3"]
    assert [d["ref"] for d in report["approved_spec"]["decisions"]] == ["D-1", "D-2"]
    md = api.as_("chandra").get(f"{api.base(SLUG)}/drift", params={"task": "T-1", "format": "md"}).text
    assert "## Drift since baseline B-1" in md and "**3 changes · 3 explained · 0 unexplained**" in md

    # ── touchpoint 3: the PR, the engg approval, the deploy guard ─────────
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "https://github.com/acme/orders/pull/77", "pr_sha": "abc123"}}])
    api.write(
        SLUG,
        [
            {
                "type": "test_run",
                "fields": {
                    "summary": "integration + unit suite",
                    "level": "integration",
                    "result": "GREEN",
                    "at_sha": "abc123",
                    "run_url": "https://ci.acme.dev/runs/9",
                    "run_on": "2026-10-31T15:00",
                    "task": ["T-1"],
                    "covers": [{"ac": ac, "result": "GREEN", "test_id": f"test_{ac.lower()}"} for ac in ("AC-1", "AC-2", "AC-3", "AC-4")],
                },
            }
        ],
    )
    gpr = api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]
    assert gpr["failing_rules"] == ["approval_by_role"]
    assert [x["ref"] for x in api.inbox("priya")["items"]] == ["T-1"]
    approval = api.approve(SLUG, "T-1", "engg", "priya", at_sha="abc123")
    apr = api.record(SLUG, approval["results"][0]["ref"])
    assert apr["fields"]["drift_digest"] == report["digest"] and apr["status"] == "CURRENT"
    assert api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]["status"] == "PASSED"
    go = api.get("/api/deploy-guard", initiative_id=api.id(SLUG), task="T-1", sha="abc123", environment="staging")
    assert go["decision"] == "GO", go["reasons"]
    assert api.get("/api/deploy-guard", initiative_id=api.id(SLUG), task="T-1", sha="fff999", environment="staging")["decision"] == "NO-GO"

    # ── a later spec change moves the digest: the approval goes stale ─────
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "AC-4 threshold should be 10s", "severity": "minor", "target": ["AC-4"], "at_sha": "abc123"}}], who=api.as_("priya"))
    api.write(SLUG, [{"ref": "AC-4", "fields": {"text": "Given a row update, when CDC lags more than 10s, then the lag alert fires"}, "because": ["F-1"]}])
    assert api.record(SLUG, apr["ref"])["status"] == "STALE"
    nogo = api.get("/api/deploy-guard", initiative_id=api.id(SLUG), task="T-1", sha="abc123", environment="staging")
    assert nogo["decision"] == "NO-GO"
    assert any(r.startswith("GATE_PR") for r in nogo["reasons"])
    assert api.drift(SLUG, task="T-1")["summary"]["unexplained"] == 0

    # ── a cause that stops explaining makes the drift UNEXPLAINED ─────────
    api.write(SLUG, [{"ref": "F-1", "fields": {"resolution": "rejected", "resolution_note": "5s is the SLO"}}], who=api.as_("priya"))
    report = api.drift(SLUG, task="T-1")
    assert report["status"] == "UNEXPLAINED"
    assert [e["ref"] for e in report["entries"] if not e["explained"]] == ["AC-4"]
    assert api.record(SLUG, "draft")["status"] == "REOPENED"
    assert "drift_explained_for_task" in api.get(f"{api.base(SLUG)}/tasks/T-1/gates")[0]["failing_rules"]
