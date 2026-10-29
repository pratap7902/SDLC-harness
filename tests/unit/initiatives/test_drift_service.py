"""DriftService: entries, explanations, task scoping, spec diff, digest, baselines."""

import pytest

from app.blueprint.services.blueprint_loader import get_blueprint
from app.initiatives.services.drift_service import DriftService, spec_moved
from tests.fixtures.slice import SLUG, task_op, to_baseline, to_task


def kinds(report):
    return [(e["kind"], e["ref"], e["explained"]) for e in report["entries"]]


def test_spec_moved_counts_first_fills_and_removals():
    bp = get_blueprint()
    assert spec_moved(bp, "draft", {"hld": "a"}, {"hld": "a", "lld": "new"}) == ["lld: (empty) → “new”"]
    assert spec_moved(bp, "draft", {"hld": "a", "lld": "x"}, {"hld": "a"}) == ["lld: “x” → (removed)"]
    assert spec_moved(bp, "draft", {"scope_in": ["a"]}, {"scope_in": ["a", "b"]}) == ["scope_in (+1 −0)"]
    assert spec_moved(bp, "draft", {"problem": "a"}, {"problem": "b"}) == []  # not material


def test_no_baseline_yet(api):
    api.start()
    report = api.drift(SLUG)
    assert report["status"] == "NO_BASELINE" and report["entries"] == []


def test_a_clean_baseline(api):
    to_baseline(api)
    report = api.drift(SLUG)
    assert report["status"] == "CLEAN"
    assert report["baseline"]["ref"] == "B-1" and report["baseline"]["approved_by"] == "chandra"
    assert report["summary"]["changes"] == 0
    assert [d["ref"] for d in report["approved_spec"]["decisions"]] == ["D-1", "D-2"]
    assert report["approved_spec"] == report["current_spec"]


def test_an_agent_cannot_edit_the_spec_without_because_but_a_human_can(api):
    to_baseline(api)
    errors = api.rejected(SLUG, [{"ref": "draft", "fields": {"lld": "Relay polls every 5s."}}])
    assert any("spec change after baseline B-1 needs `because`" in e for e in errors)
    api.write(SLUG, [{"ref": "draft", "fields": {"lld": "Table order_outbox; relay polls every 5s.\nIndexes on order_id."}}], who=api.as_("chandra"))
    report = api.drift(SLUG)
    assert kinds(report) == [("draft_edited", "draft", True)]
    entry = report["entries"][0]
    assert entry["actor_kind"] == "human" and entry["explanation"][0]["why"] == "made by a human (chandra)"
    lld = report["spec_diff"]["draft"]["lld"]
    assert lld["added"] == 2 and lld["removed"] == 1
    assert "+Indexes on order_id." in lld["diff"]


def test_agent_edits_are_explained_by_a_finding_and_unexplained_once_it_is_rejected(api):
    to_baseline(api)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "lld misses the index", "severity": "minor", "target": ["draft"]}}], who=api.as_("priya"))
    api.write(SLUG, [{"ref": "draft", "fields": {"lld": "Table order_outbox with an index on order_id."}, "because": ["F-1"]}])
    report = api.drift(SLUG)
    assert kinds(report) == [("draft_edited", "draft", True)]
    assert report["entries"][0]["because"] == ["F-1"]
    assert api.record(SLUG, "draft")["status"] == "APPROVED"
    api.write(SLUG, [{"ref": "F-1", "fields": {"resolution": "rejected", "resolution_note": "the index exists"}}], who=api.as_("priya"))
    report = api.drift(SLUG)
    assert report["status"] == "UNEXPLAINED"
    assert report["entries"][0]["explanation"][0]["why"] == "F-1 was rejected"
    assert api.record(SLUG, "draft")["status"] == "REOPENED"
    gate = next(g for g in api.state(SLUG)["gates"] if g["gate"] == "GATE_DRAFT")
    assert gate["status"] == "BLOCKED"


def test_a_decision_taken_after_the_baseline_needs_a_grounded_because(api):
    to_baseline(api)
    new = {"type": "decision", "title": "Retention", "fields": {"question": "How long do outbox rows live?", "domain": "engg", "level": "SHOULD", "verdict": "7 days", "provisional": "yes"}}
    errors = api.rejected(SLUG, [new])
    assert any("needs `because`" in e for e in errors)
    # an open question needs no because — it changes nothing yet; it shows as pending
    api.write(SLUG, [{"type": "decision", "title": "Retention", "fields": {"question": "How long do outbox rows live?", "domain": "engg", "level": "SHOULD"}}])
    assert api.drift(SLUG)["pending_decisions"][0]["ref"] == "D-3"
    # grounded by an approved decision (a baseline member)
    api.write(SLUG, [{"ref": "D-3", "fields": {"verdict": "7 days", "provisional": "yes"}, "because": ["D-1"]}])
    report = api.drift(SLUG)
    assert kinds(report) == [("decision_added", "D-3", True)]
    assert report["entries"][0]["explanation"][0]["why"].startswith("approved in B-1")
    assert report["spec_diff"]["decisions"]["added"] == [{"ref": "D-3", "verdict": "7 days", "status": "PROVISIONAL"}]


def test_a_human_confirming_a_provisional_member_is_evidence(api):
    api.start()
    from tests.fixtures.slice import draft_batch

    batch = draft_batch()
    batch[1]["fields"]["provisional"] = "yes"
    batch[1]["fields"]["escalated"] = "no"
    api.write(SLUG, batch)
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    api.write(SLUG, [{"ref": "D-2", "fields": {"rationale": "per G-1"}, "note": "per G-1"}])
    api.approve(SLUG, "draft", "dri", "chandra")
    verdict = api.record(SLUG, "D-2")["fields"]["verdict"]
    api.ok(api.as_("priya").post(f"{api.base(SLUG)}/decisions/D-2/rule", json={"verdict": verdict, "rationale": "Confirmed with billing."}))
    report = api.drift(SLUG)
    assert kinds(report) == [("decision_confirmed", "D-2", True)]
    assert api.record(SLUG, "D-2")["status"] == "DECIDED"


def test_retiring_an_ac_is_a_human_act_and_shows_in_the_diff(api):
    to_baseline(api)
    assert api.agent().post(f"{api.base(SLUG)}/criteria/AC-2/retire", json={"because": "x"}).status_code == 403
    api.ok(api.as_("chandra").post(f"{api.base(SLUG)}/criteria/AC-2/retire", json={"because": "relay latency is an SLO, not an AC"}))
    report = api.drift(SLUG)
    assert kinds(report) == [("ac_retired", "AC-2", True)]
    assert report["spec_diff"]["criteria"]["retired"][0]["ref"] == "AC-2"
    assert "AC-2" not in [c["ref"] for c in report["current_spec"]["criteria"]]


def test_task_scope_digest_and_other_changes(api):
    to_task(api)
    t2 = task_op()
    t2["title"] = "Envelope"
    t2["fields"].update(implements=["D-2"], covers=["AC-3"])
    api.write(SLUG, [t2])
    d1, d2 = api.drift(SLUG, task="T-1")["digest"], api.drift(SLUG, task="T-2")["digest"]
    assert api.drift(SLUG, task="T-1")["digest"] == d1  # stable
    # a change in T-1's scope only (AC-1 is covered by T-1, sourced from D-1)
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "AC-1 too vague", "severity": "minor", "target": ["AC-1"]}}], who=api.as_("priya"))
    api.write(SLUG, [{"ref": "AC-1", "fields": {"text": "Given an order update, when it commits, then exactly one outbox row with the new state is written"}, "because": ["F-1"]}])
    r1, r2 = api.drift(SLUG, task="T-1"), api.drift(SLUG, task="T-2")
    assert kinds(r1) == [("ac_changed", "AC-1", True)] and r1["digest"] != d1
    assert r1["spec_diff"]["criteria"]["changed"][0]["ref"] == "AC-1"
    assert r2["entries"] == [] and r2["summary"]["other_changes"] == 1 and r2["digest"] == d2
    assert "AC-1" not in r2["scope_refs"] and "AC-3" in r2["scope_refs"]


def test_reapproval_starts_a_new_baseline_and_old_reports_stop_at_it(api):
    to_baseline(api)
    out = api.write(SLUG, [{"ref": "draft", "fields": {"lld": "v2 lld"}}], who=api.as_("chandra"))
    # the edit queued the ACs that rest on the draft: they are re-read before re-approval
    assert sorted(x.split(" ")[0] for x in out["review_items"]) == ["AC-1", "AC-2", "AC-3"]
    api.write(SLUG, [{"ref": ac, "reviewed": True, "note": "lld detail only"} for ac in ("AC-1", "AC-2", "AC-3")], who=api.as_("chandra"))
    api.approve(SLUG, "draft", "dri", "chandra")
    state = api.state(SLUG)
    assert state["baseline"]["ref"] == "B-2"
    assert api.drift(SLUG)["status"] == "CLEAN"
    old = api.drift(SLUG, baseline="B-1")
    assert old["until"] == "B-2" and kinds(old) == [("draft_edited", "draft", True)]
    assert old["current_spec"]["draft"]["lld"] == "v2 lld"
    assert [b["status"] for b in api.get(f"{api.base(SLUG)}/draft")["baselines"]] == ["SUPERSEDED", "CURRENT"]


def test_repinning_the_requirement_is_a_human_material_change(api):
    to_baseline(api)
    assert api.agent().post(f"{api.base(SLUG)}/snapshot", json={"requirement": "x"}).status_code == 403
    out = api.ok(api.as_("chandra").post(f"{api.base(SLUG)}/snapshot", json={"requirement": "# Order events v2\nAlso emit refunds."}))
    assert out["write"]["review_items"][0].startswith("draft ← initiative: snapshot_hash")
    report = api.drift(SLUG)
    assert kinds(report) == [("requirement_repinned", "initiative", True)]
    snap = api.state(SLUG)["initiative"]["spec_snapshot"]
    assert snap["requirement"].startswith("# Order events v2") and snap["previous_hash"]


def test_cause_ok_walks_one_chain(api, db_session):
    to_baseline(api)
    from app.initiatives.services.record_service import RecordService

    records = RecordService(db_session)
    g = records.graph(records.initiative(SLUG))
    service = DriftService(records.bp)
    assert service.cause_ok(g, "G-1").ok
    assert service.cause_ok(g, "D-1").why.startswith("approved in B-1")
    assert not service.cause_ok(g, "G-9").ok
    assert service.cause_ok(g, "AC-1").why.endswith("a change is explained by a gap, a decision or a finding")


@pytest.mark.parametrize("fmt", ["md", "text"])
def test_renderings(api, fmt):
    to_baseline(api)
    text = api.as_("chandra").get(f"{api.base(SLUG)}/drift", params={"format": fmt}).text
    assert "B-1" in text
