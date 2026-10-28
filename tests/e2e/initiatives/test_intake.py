"""Starting a feature inside the service (POST /api/initiatives, MCP create_initiative)."""

import hashlib
import json


def test_start_pins_the_requirement_and_assigns_people(api):
    out = api.start(slug=None, title="Order events: outbox!", work_item_url=None, product=None, qa=None)
    i = out["initiative"]
    assert i["slug"] == "order-events-outbox"
    snap = i["spec_snapshot"]
    assert snap["requirement"].startswith("# Order events") and snap["work_item_url"] is None
    assert snap["created_by"] == "chandra"
    assert i["snapshot_hash"] == hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
    assert [(a["ref"], a["role"], a["person"]) for a in out["assignments"]] == [("A-1", "dri", "chandra"), ("A-2", "engg", "priya")]
    record = api.record("order-events-outbox", "initiative")
    assert record["fields"]["snapshot_hash"] == i["snapshot_hash"] and record["title"] == "Order events: outbox!"
    assert out["phase"] == "DRAFT"
    assert [c["disposition"] for c in out["catalog"]["intake"]] == ["addressed"] * 3


def test_slugs_dedupe_unless_given(api):
    api.start(slug=None)
    second = api.start(slug=None)
    assert second["initiative"]["slug"] == "order-events-outbox-2"
    r = api.as_("chandra").post("/api/initiatives", json={"title": "x", "slug": "order-events-outbox", "requirement": "r", "dri": "a", "engg": "b"})
    assert r.status_code == 409


def test_validation(api):
    r = api.as_("chandra").post("/api/initiatives", json={"title": "x", "requirement": "  ", "dri": "a", "engg": ""})
    assert r.status_code == 422
    assert r.json()["error_data"]["errors"] == ["requirement: required — the markdown the feature starts from", "engg: required — a person's handle"]
    r = api.as_("chandra").post("/api/initiatives", json={"title": "x", "requirement": "r", "dri": "a", "engg": "b", "slug": "Bad Slug"})
    assert r.status_code == 422
    assert api.as_("chandra").post("/api/initiatives", json={"title": "x"}).status_code == 422


def test_list(api):
    api.start()
    rows = api.get("/api/initiatives")
    assert rows[0]["slug"] == "order-events" and rows[0]["phase"] == "DRAFT"
    assert rows[0]["dri"] == "chandra" and rows[0]["baseline"] is None and rows[0]["drift"] is None
    assert rows[0]["work_item_url"].startswith("https://dev.azure.com/")


def test_unknown_initiative_is_404(api):
    r = api.as_("chandra").get("/api/initiatives/999999")
    assert r.status_code == 404 and "No initiative 999999" in r.json()["detail"]
