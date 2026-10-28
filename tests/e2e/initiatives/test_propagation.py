"""The review queue: a material change queues what rests on it, routed by domain."""

from tests.fixtures.slice import SLUG, draft_batch, to_task


def test_a_gap_answer_queues_what_it_blocks_routed_to_the_domain_assignee(api):
    api.start()
    api.write(SLUG, draft_batch())
    out = api.answer(SLUG, "G-1", choice="yes", person="maya")
    assert out["review_items"] == ["D-2 ← G-1: status OPEN → ANSWERED (→ priya)"]
    items = api.get(f"/api/initiatives/{SLUG}/reviews")
    assert [(i["target"], i["path"], i["domain"]) for i in items] == [("D-2", "link", "engg")]
    assert [x["ref"] for x in api.get("/api/inbox/priya")["items"] if x["kind"] == "review_item"] == [str(items[0]["id"])]


def test_upheld_stops_the_ripple_and_revised_closes_on_edit(api):
    api.start()
    api.write(SLUG, draft_batch())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    out = api.write(SLUG, [{"ref": "D-2", "reviewed": True, "note": "already partitioned by order_id"}])
    assert out["results"][0]["action"] == "reviewed" and out["review_items"] == []
    closed = api.get(f"/api/initiatives/{SLUG}/reviews", status="upheld")
    assert closed[0]["note"] == "already partitioned by order_id"
    errors = api.rejected(SLUG, [{"ref": "D-2", "reviewed": True}])
    assert errors == ["note: required with reviewed — say what you checked it against"]


def test_editing_a_material_field_queues_dependents_one_hop(api):
    to_task(api)
    out = api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "u", "pr_sha": "s1"}}])
    out = api.write(SLUG, [{"ref": "T-1", "fields": {"pr_sha": "s2"}}])
    assert out["review_items"] == []  # nothing rests on a task here
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "AC-1 wording", "severity": "minor", "target": ["AC-1"]}}])
    out = api.write(SLUG, [{"ref": "AC-1", "fields": {"text": "Given an order update, when it commits, then one outbox row is written"}, "because": ["F-1"]}])
    assert len(out["review_items"]) == 1
    assert out["review_items"][0].startswith("T-1 ← AC-1: text: “Given an order update")
    assert out["review_items"][0].endswith("(→ priya)")


def test_resolve_endpoint(api):
    api.start()
    api.write(SLUG, draft_batch())
    api.answer(SLUG, "G-1", choice="yes", person="maya")
    item = api.get(f"/api/initiatives/{SLUG}/reviews")[0]
    r = api.as_("priya").post(f"/api/initiatives/{SLUG}/reviews/{item['id']}/resolve", json={"resolution": "maybe", "note": "x"})
    assert r.status_code == 422
    done = api.ok(api.as_("priya").post(f"/api/initiatives/{SLUG}/reviews/{item['id']}/resolve", json={"resolution": "upheld", "note": "holds"}))
    assert done["status"] == "upheld" and done["resolved_by"] == "priya"
    assert api.get(f"/api/initiatives/{SLUG}/reviews") == []
