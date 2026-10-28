"""The JSON the UI pages read: shapes are a contract (docs/api.md)."""

from tests.fixtures.slice import SLUG, draft_batch, pr_open, to_task


def test_state_shape(api):
    to_task(api)
    s = api.state(SLUG)
    assert set(s) == {"initiative", "phase", "assignments", "gates", "tasks", "counts", "open", "stuck", "baseline", "drift", "stale", "catalog"}
    assert [g["gate"] for g in s["gates"]] == ["GATE_DRAFT", "GATE_VALIDATED"]
    assert s["tasks"][0]["gate_pr"]["status"] == "BLOCKED" and s["tasks"][0]["drift"]["changes"] == 0
    assert s["counts"]["decision"] == {"DECIDED": 2}
    assert set(s["catalog"]) == {"intake", "draft", "plan", "build"}


def test_draft_page_shape(api):
    api.start()
    api.write(SLUG, draft_batch())
    page = api.get(f"{api.base(SLUG)}/draft")
    assert set(page) == {"initiative", "draft", "decisions", "criteria", "gaps", "catalog", "gate", "can_approve", "approver", "approval_blockers", "approvals", "baselines", "review_items"}
    assert page["approver"] == "chandra"
    d1 = page["decisions"][0]
    assert d1["ref"] == "D-1" and d1["sourced_acs"] == ["AC-1", "AC-2"] and d1["superseded_by"] == []
    assert d1["fields"]["options"][0]["name"] == "outbox"
    assert page["draft"]["fields"]["decisions"] == ["D-1", "D-2"]


def test_task_page_records_and_activity(api):
    to_task(api)
    pr_open(api)
    page = api.get(f"{api.base(SLUG)}/tasks/T-1")
    assert set(page) == {"task", "gate", "drift", "approver", "test_runs", "findings", "deploys"}
    assert page["approver"] == "priya" and page["test_runs"][0]["ref"] == "R-1"
    assert page["drift"]["task"] == "T-1"
    decisions = api.get(f"{api.base(SLUG)}/records", type="decision")
    assert [d["ref"] for d in decisions] == ["D-1", "D-2"]
    assert api.get(f"{api.base(SLUG)}/records", q="partition")[0]["ref"] == "D-2"
    assert api.get(f"{api.base(SLUG)}/records", status="ANSWERED")[0]["ref"] == "G-1"
    feed = api.get(f"{api.base(SLUG)}/activity", limit=5)
    assert feed[0]["ref"] == "R-1" and feed[0]["actor_kind"] == "agent"
    approvals = api.get(f"{api.base(SLUG)}/activity", ref="APR-1")
    assert approvals[0]["actor"] == "chandra" and approvals[0]["actor_kind"] == "human"
    events = api.get(f"{api.base(SLUG)}/events")
    kinds = {e["kind"] for e in events}
    assert {"initiative_created", "record_written", "baseline_created", "review_item_queued", "gate_changed"} <= kinds
    since = events[-3]["id"]
    assert [e["id"] for e in api.get(f"{api.base(SLUG)}/events", since=since)] == [e["id"] for e in events[-2:]]


def test_404s(api):
    api.start()
    c = api.as_("chandra")
    assert c.get(f"{api.base(SLUG)}/records/D-9").status_code == 404
    assert c.get(f"{api.base(SLUG)}/tasks/T-9").status_code == 404
    assert c.get(f"{api.base(SLUG)}/drift", params={"task": "T-9"}).status_code == 404
