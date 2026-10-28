"""Gates over the REST surface: what blocks, and when they pass."""

from tests.fixtures.slice import SLUG, draft_batch, pr_open, to_task


def gate(api, key):
    return next(g for g in api.get(f"/api/initiatives/{SLUG}/gates") if g["gate"] == key)


def test_gate_draft_progression(api):
    api.start()
    g = gate(api, "GATE_DRAFT")
    assert g["status"] == "BLOCKED" and g["human_role"] == "dri"
    catalog = next(r for r in g["rules"] if r["name"] == "catalog_addressed")
    assert catalog["failing"] == ["security_review", "rollback_plan", "observability", "data_migration_assessed", "test_strategy"]
    batch = draft_batch()
    batch[5]["fields"]["source"] = ["#0"]  # AC-3 no longer sourced from D-2
    api.write(SLUG, batch)
    rules = {r["name"]: r["failing"] for r in gate(api, "GATE_DRAFT")["rules"] if not r["passed"]}
    assert rules == {"no_open_gap_blocking_draft": ["G-1"], "every_decision_covered_by_an_ac": ["D-2"], "approval_by_role": []}
    assert api.get(f"/api/initiatives/{SLUG}/draft")["can_approve"] is False


def test_gate_pr_and_gate_validated(api):
    to_task(api)
    assert gate(api, "GATE_VALIDATED")["failing_rules"] == ["every_ac_green"]
    pr_open(api)
    gates = api.get(f"/api/initiatives/{SLUG}/tasks/T-1/gates")
    assert [g["gate"] for g in gates] == ["GATE_PR"] and gates[0]["failing_rules"] == ["approval_by_role"]
    api.approve(SLUG, "T-1", "engg", "priya")
    assert api.get(f"/api/initiatives/{SLUG}/tasks/T-1/gates")[0]["status"] == "PASSED"
    assert gate(api, "GATE_VALIDATED")["status"] == "PASSED"
    # a new push un-passes the gate: the approval is pinned to the old sha
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_sha": "def456"}}])
    g = api.get(f"/api/initiatives/{SLUG}/tasks/T-1/gates")[0]
    assert g["status"] == "BLOCKED" and "approval_by_role" in g["failing_rules"]


def test_phases_follow_the_gates(api):
    to_task(api)
    assert api.state(SLUG)["phase"] == "BUILD"
    pr_open(api)
    api.approve(SLUG, "T-1", "engg", "priya")
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "merged"}}])
    state = api.state(SLUG)
    assert state["tasks"][0]["status"] == "DONE"
    assert state["phase"] == "SHIP"


def test_a_manual_ac_needs_qa(api):
    to_task(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "needs a manual check", "severity": "minor", "target": ["T-1"]}}])
    api.write(SLUG, [{"type": "acceptance_criterion", "fields": {"text": "Ops can replay a day of events by hand", "level": "manual", "manual": "yes", "source": ["D-1"]}, "because": ["F-1"]}])
    api.write(SLUG, [{"ref": "T-1", "fields": {"covers": ["AC-1", "AC-2", "AC-3", "AC-4"]}}])
    pr_open(api)
    assert next(r for r in gate(api, "GATE_VALIDATED")["rules"] if r["name"] == "manual_acs_signed_by")["failing"] == ["AC-4"]
    assert [x["ref"] for x in api.get("/api/inbox/sam")["items"]] == ["AC-4"]
    r = api.as_("priya").post(f"/api/initiatives/{SLUG}/criteria/AC-4/sign", json={"at_sha": "abc123"})
    assert r.status_code == 422 and "not the qa" in r.json()["detail"]
    api.ok(api.as_("sam").post(f"/api/initiatives/{SLUG}/criteria/AC-4/sign", json={"at_sha": "abc123"}))
    assert gate(api, "GATE_VALIDATED")["status"] == "PASSED"
