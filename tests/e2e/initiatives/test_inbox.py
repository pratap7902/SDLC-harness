"""The inbox: one person's lane across initiatives, overdue first."""

from datetime import timedelta

from app.initiatives.models.record import Record
from tests.fixtures.slice import SLUG, draft_batch


def test_items_are_routed_and_carry_what_the_human_needs(api):
    api.start()
    api.write(SLUG, draft_batch())
    inbox = api.get("/api/inbox/maya")
    item = inbox["items"][0]
    assert (inbox["count"], item["kind"], item["ref"], item["initiative"]) == (1, "gap", "G-1", SLUG)
    assert item["options"][0]["key"] == "yes" and item["recommendation"] == "yes"
    assert item["blocks"] == ["D-2"] and item["sla_hours"] == 24 and item["overdue"] is False
    assert api.get("/api/inbox/chandra")["count"] == 0


def test_overdue_items_sort_first(api, db_session):
    api.start()
    api.start(slug="refunds", title="Refund events")
    gap = {"type": "gap", "title": "g", "fields": {"question": "q?", "kind": "unknown", "domain": "product", "asked_by": "r", "why_now": "n", "context": "c"}}
    api.write(SLUG, [gap])
    api.write("refunds", [gap])
    old = db_session.query(Record).filter(Record.ref == "G-1").order_by(Record.id.asc()).first()
    old.created_at = old.created_at - timedelta(hours=30)
    db_session.commit()
    inbox = api.get("/api/inbox/maya")
    assert [(x["initiative"], x["overdue"]) for x in inbox["items"]] == [(SLUG, True), ("refunds", False)]
    assert inbox["overdue"] == 1


def test_answer_validation(api):
    api.start()
    api.write(SLUG, draft_batch())
    maya = api.as_("maya")
    r = maya.post(f"/api/initiatives/{SLUG}/gaps/G-1/answer", json={"choice": "maybe"})
    assert r.status_code == 422 and "not an option" in r.json()["detail"]
    r = maya.post(f"/api/initiatives/{SLUG}/gaps/G-1/answer", json={})
    assert r.status_code == 422
    out = api.answer(SLUG, "G-1", choice="yes", person="maya")
    g1 = api.record(SLUG, "G-1")
    assert g1["fields"]["answer"] == "Yes, per order" and g1["fields"]["choice"] == "yes" and g1["fields"]["answered_by"] == "maya"
    assert out["ok"] is True
    r = maya.post(f"/api/initiatives/{SLUG}/gaps/G-1/answer", json={"answer": "again"})
    assert r.status_code == 422 and "ANSWERED" in r.json()["detail"]


def test_people(api):
    api.start()
    api.write(SLUG, draft_batch())
    people = {p["person"]: p for p in api.get("/api/people")}
    assert people["maya"]["inbox"] == 1
    assert {"initiative": SLUG, "role": "dri"} in people["chandra"]["roles"]
