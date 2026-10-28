"""GET /api/overview: the Features list in one read."""

from tests.fixtures.slice import SLUG, deviation_gap, draft_batch, pr_open, to_task


def test_overview_draft_phase_waits_on_people(api):
    api.start()
    api.write(SLUG, draft_batch())
    o = api.get("/api/overview", person="maya")
    assert set(o) == {"person", "summary", "initiatives", "waiting", "decisions", "my_pr_approvals"}
    row = o["initiatives"][0]
    assert row["slug"] == SLUG and row["phase"] == "DRAFT" and row["dri"] == "chandra"
    assert row["people"] == {"dri": "chandra", "engg": "priya", "product": "maya", "qa": "sam"}
    assert row["involved"] is True
    assert row["gate_draft"]["state"] == "waiting" and row["baseline"] is None and row["drift"] is None
    # G-1 is maya's (product): it is the next item, and first in the decisions list
    assert row["next"]["person"] == "maya" and row["next"]["ref"] == "G-1" and row["next"]["label"] == "G-1 · gap"
    assert o["decisions"][0]["ref"] == "G-1" and o["summary"]["decisions_waiting"] == len(o["decisions"])
    assert row["updated_at"] and row["prs"] == {"total": 0, "approved": 0, "approved_refs": [], "stale": [], "with_pr": 0, "done": 0}
    assert api.get("/api/overview", person="nobody")["initiatives"][0]["involved"] is False


def test_overview_pr_approvals_and_staleness(api):
    to_task(api)
    pr_open(api, sha="abc123")
    o = api.get("/api/overview", person="priya")
    row = o["initiatives"][0]
    assert row["gate_draft"]["state"] == "approved" and row["baseline"] == "B-1"
    assert row["drift"]["changes"] == 0
    # T-1's PR is open, tested: the engg approval is waiting on priya
    assert [a["target"] for a in o["my_pr_approvals"]] == ["T-1"]
    assert all(d["kind"] != "approval" or d["target"] == "draft" for d in o["decisions"])
    api.approve(SLUG, "T-1", "engg", "priya", at_sha="abc123")
    row = api.get("/api/overview", person="priya")["initiatives"][0]
    assert row["prs"]["approved"] == 1 and row["prs"]["total"] == 1 and row["prs"]["stale"] == []
    # a new push makes the approval stale
    pr_open(api, sha="def456")
    row = api.get("/api/overview", person="priya")["initiatives"][0]
    assert row["prs"]["approved"] == 0 and row["prs"]["stale"] == ["T-1"]


def test_overview_agents_lane_and_leases(api):
    to_task(api)
    row = api.get("/api/overview")["initiatives"][0]
    assert row["agents"]["queued"] >= 1 and row["agents"]["leased"] == 0
    assert {"kind": "task", "ref": "T-1", "holder": None} in row["agents"]["working"]
    api.ok(api.agent().post("/api/leases/claim", json={"item_key": f"task:{SLUG}:T-1"}))
    row = api.get("/api/overview")["initiatives"][0]
    assert row["agents"]["leased"] == 1 and row["agents"]["holders"] == ["runner-sdk"]


def test_overview_open_deviation_is_next(api):
    to_task(api)
    api.write(SLUG, [deviation_gap()])
    o = api.get("/api/overview", person="priya")
    row = o["initiatives"][0]
    assert row["next"]["ref"] == "G-2" and row["next"]["person"] == "priya" and row["next"]["kind"] == "gap"
    assert o["decisions"][0]["ref"] == "G-2"
