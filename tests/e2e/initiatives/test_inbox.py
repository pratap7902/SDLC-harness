"""The inbox: one person's lane across initiatives, overdue first."""

from datetime import timedelta

from app.initiatives.models.record import Record
from tests.fixtures.slice import SLUG, draft_batch


def test_items_are_routed_and_carry_what_the_human_needs(api):
    api.start()
    api.write(SLUG, draft_batch())
    inbox = api.inbox("maya")
    item = inbox["items"][0]
    assert (inbox["count"], item["kind"], item["ref"], item["initiative"]) == (1, "gap", "G-1", SLUG)
    assert item["options"][0]["key"] == "yes" and item["recommendation"] == "yes"
    assert item["blocks"] == ["D-2"] and item["sla_hours"] == 24 and item["overdue"] is False
    assert api.inbox("chandra")["count"] == 0


def test_overdue_items_sort_first(api, db_session):
    api.start()
    api.start(slug="refunds", title="Refund events")
    gap = {"type": "gap", "title": "g", "fields": {"question": "q?", "kind": "unknown", "domain": "product", "asked_by": "r", "why_now": "n", "context": "c"}}
    api.write(SLUG, [gap])
    api.write("refunds", [gap])
    old = db_session.query(Record).filter(Record.ref == "G-1").order_by(Record.id.asc()).first()
    old.created_at = old.created_at - timedelta(hours=30)
    db_session.commit()
    inbox = api.inbox("maya")
    assert [(x["initiative"], x["overdue"]) for x in inbox["items"]] == [(SLUG, True), ("refunds", False)]
    assert inbox["overdue"] == 1


def test_answer_validation(api):
    api.start()
    api.write(SLUG, draft_batch())
    maya = api.as_("maya")
    r = maya.post(f"{api.base(SLUG)}/gaps/G-1/answer", json={"choice": "maybe"})
    assert r.status_code == 422 and "not an option" in r.json()["detail"]
    r = maya.post(f"{api.base(SLUG)}/gaps/G-1/answer", json={})
    assert r.status_code == 422
    out = api.answer(SLUG, "G-1", choice="yes", person="maya")
    g1 = api.record(SLUG, "G-1")
    assert g1["fields"]["answer"] == "Yes, per order" and g1["fields"]["choice"] == "yes" and g1["fields"]["answered_by"] == "maya"
    assert out["ok"] is True
    r = maya.post(f"{api.base(SLUG)}/gaps/G-1/answer", json={"answer": "again"})
    assert r.status_code == 422 and "ANSWERED" in r.json()["detail"]


def test_people(api):
    api.start()
    api.write(SLUG, draft_batch())
    people = {p["person"]: p for p in api.get("/api/people")}
    assert people["maya"]["inbox"] == 1
    assert {"initiative": SLUG, "role": "dri"} in people["chandra"]["roles"]


def test_any_human_may_answer_a_gap_and_both_people_are_recorded(api):
    from tests.fixtures.slice import deviation_gap, to_task

    to_task(api)
    api.write(SLUG, [deviation_gap()])  # G-2, domain engg → routed to priya
    assert [x["ref"] for x in api.inbox("priya")["items"] if x["kind"] == "gap"] == ["G-2"]
    assert not [x for x in api.inbox("chandra")["items"] if x["kind"] == "gap"]
    # chandra is not the assignee; the body cannot claim to be someone else
    out = api.ok(api.as_("chandra").post(f"{api.base(SLUG)}/gaps/G-2/answer", json={"choice": "cdc", "answered_by": "mallory"}))
    assert out["results"][0]["status"] == "ANSWERED"
    f = api.record(SLUG, "G-2")["fields"]
    assert (f["answered_by"], f["assigned_to"], f["assigned_role"], f["answered_for"]) == ("chandra", "priya", "engg", "priya")
    assert f["answered_on"]
    entry = next(e for e in api.drift(SLUG)["entries"] if e["kind"] == "gap_answered")
    assert entry["summary"].startswith("G-2 answered by chandra · assigned to priya")
    assert (entry["detail"]["assigned_to"], entry["detail"]["answered_for"], entry["actor"]) == ("priya", "priya", "chandra")
    feed = api.get(f"{api.base(SLUG)}/activity", ref="G-2")
    answered = next(x for x in feed if x.get("assigned_to"))
    assert (answered["answered_by"], answered["assigned_to"], answered["answered_for"]) == ("chandra", "priya", "priya")
    history = api.get(f"{api.base(SLUG)}/records/G-2/history")
    assert history[0]["fields"]["answered_for"] == "priya"


def test_the_assignee_answering_records_no_answered_for(api):
    api.start()
    api.write(SLUG, draft_batch())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    f = api.record(SLUG, "G-1")["fields"]
    assert (f["answered_by"], f["assigned_to"]) == ("maya", "maya") and "answered_for" not in f


def test_agents_still_cannot_answer(api):
    api.start()
    api.write(SLUG, draft_batch())
    r = api.agent().post(f"{api.base(SLUG)}/gaps/G-1/answer", json={"choice": "yes"})
    assert r.status_code == 403 and r.json()["error_code"] == "HUMAN_ONLY"
    assert api.record(SLUG, "G-1")["status"] == "OPEN"
