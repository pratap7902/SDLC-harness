"""next_work is the pipeline's cursor; leases keep two runners off one item."""

from datetime import timedelta

from app.core.utils.time import utcnow
from app.initiatives.models.lease import Lease
from tests.fixtures.slice import SLUG, to_task


def test_draft_work_comes_first_in_a_new_initiative(api):
    api.start()
    out = api.get(f"{api.base(SLUG)}/next-work")
    assert [x["key"] for x in out["items"]] == [f"draft:{api.id(SLUG)}"]
    assert [c["item"] for c in out["items"][0]["context"]["catalog"]][:2] == ["security_review", "rollback_plan"]


def test_a_claimed_item_is_hidden_from_a_second_caller_and_expiry_returns_it(api, db_session):
    to_task(api)
    a, b = api.as_("runner-a", "agent"), api.as_("runner-b", "agent")
    work = api.ok(a.get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))
    key = work["items"][0]["key"]
    assert key == f"task:{api.id(SLUG)}:T-1"
    assert work["items"][0]["context"]["record"]["ref"] == "T-1"
    assert set(work["items"][0]["context"]["cites"]) == {"D-1", "D-2", "AC-1", "AC-2", "AC-3"}
    lease = api.ok(a.post("/api/leases/claim", json={"item_key": key, "ttl_min": 5}))
    assert lease["holder"] == "runner-a"
    assert api.ok(b.get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"] == []
    assert api.ok(a.get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"] == []  # IN_PROGRESS now
    held = b.post("/api/leases/claim", json={"item_key": key})
    assert held.status_code == 409 and held.json()["error_data"]["holder"] == "runner-a"
    assert api.ok(a.post(f"/api/leases/{key}/heartbeat", json={"ttl_min": 10}))["holder"] == "runner-a"
    assert b.post(f"/api/leases/{key}/heartbeat").status_code == 404
    # expiry is evaluated on read: no sweeper
    db_session.get(Lease, key).expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert [x["key"] for x in api.ok(b.get(f"{api.base(SLUG)}/next-work", params={"kind": "task"}))["items"]] == [key]
    assert api.ok(b.post("/api/leases/claim", json={"item_key": key}))["holder"] == "runner-b"
    assert api.ok(b.delete(f"/api/leases/{key}"))["released"] is True


def test_worklist_groups_both_lanes(api):
    api.start()
    from tests.fixtures.slice import draft_batch

    api.write(SLUG, draft_batch())
    wl = api.get(f"{api.base(SLUG)}/worklist")
    assert set(wl["groups"]) == {"gap", "draft"}
    gap = wl["groups"]["gap"][0]
    assert (gap["lane"], gap["person"], gap["ref"]) == ("human", "maya", "G-1")
    by_person = api.get("/api/next-work", person="maya")
    assert [x["ref"] for x in by_person["items"]] == ["G-1"]


def test_bad_kind_and_bad_key(api):
    api.start()
    assert api.agent().get(f"{api.base(SLUG)}/next-work", params={"kind": "lunch"}).status_code == 422
    assert api.agent().post("/api/leases/claim", json={"item_key": "nocolon"}).status_code == 422
