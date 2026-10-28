"""The write path: atomic batches, idempotency, base_rev, minting, `#n`, links, history."""

from tests.fixtures.slice import SLUG

GAP = {"question": "q?", "kind": "unknown", "domain": "engg", "asked_by": "runner", "why_now": "now", "context": "c"}


def test_same_batch_id_returns_the_stored_result_and_different_ops_conflict(api):
    api.start()
    first = api.write(SLUG, [{"type": "gap", "title": "one", "fields": GAP}], batch_id="batch-A")
    again = api.write(SLUG, [{"type": "gap", "title": "one", "fields": GAP}], batch_id="batch-A")
    assert again["replayed"] is True and again["results"] == first["results"]
    assert len(api.get(f"{api.base(SLUG)}/records", type="gap")) == 1
    r = api.agent().post(f"{api.base(SLUG)}/records", json={"batch_id": "batch-A", "ops": [{"type": "gap", "title": "two", "fields": GAP}]})
    assert r.status_code == 409 and r.json()["error_code"] == "BATCH_ID_REUSED"


def test_two_batches_mint_in_sequence_and_hash_refs_link_within_a_batch(api):
    api.start()
    a = api.write(SLUG, [{"type": "decision", "title": "x", "fields": {"question": "q", "domain": "engg", "level": "SHOULD"}}])
    b = api.write(
        SLUG,
        [
            {"type": "decision", "title": "y", "fields": {"question": "q", "domain": "engg", "level": "SHOULD"}},
            {"type": "acceptance_criterion", "fields": {"text": "t", "level": "unit", "source": ["#0"]}, "link": ["D-1"]},
        ],
    )
    assert a["minted"] == {"#0": "D-1"} and b["minted"] == {"#0": "D-2", "#1": "AC-1"}
    ac = api.record(SLUG, "AC-1")
    assert ac["fields"]["source"] == ["D-2"]
    assert {"kind": "source", "to": "D-2"} in ac["links"]["out"] and {"kind": "relates", "to": "D-1"} in ac["links"]["out"]
    assert {"kind": "source", "from": "AC-1"} in api.record(SLUG, "D-2")["links"]["in"]


def test_a_bad_op_rolls_back_the_whole_batch_and_gives_its_numbers_back(api):
    api.start()
    out = api.write(
        SLUG,
        [
            {"type": "gap", "title": "ok", "fields": GAP},
            {"type": "gap", "title": "bad", "fields": {**GAP, "domain": "ops"}},
            {"type": "decision", "title": "d", "fields": {"question": "q", "domain": "engg", "level": "SHOULD"}, "status": "DECIDED"},
            {"ref": "D-9", "fields": {}},
        ],
        expect=422,
    )
    results = out["error_data"]["results"]
    assert [r["action"] for r in results] == ["not saved", "error", "error", "error"]
    assert "domain: 'ops' not in product | design | engg" in results[1]["errors"]
    assert results[2]["errors"][0].startswith("status: derived, never typed")
    assert results[3]["errors"] == ["ref: D-9 does not exist in order-events — omit ref and give type to mint one"]
    assert api.get(f"{api.base(SLUG)}/records", type="gap") == []
    assert api.write(SLUG, [{"type": "gap", "title": "ok", "fields": GAP}])["minted"] == {"#0": "G-1"}


def test_base_rev_and_the_concurrent_write_window(api):
    api.start()
    api.write(SLUG, [{"type": "gap", "title": "g", "fields": GAP}])
    errors = api.rejected(SLUG, [{"ref": "G-1", "base_rev": 7, "fields": {"why_now": "later"}}])
    assert errors == ["base_rev: record is at rev 1, you sent 7 — re-read and merge"]
    other = api.as_("other-runner", "agent")
    errors = api.rejected(SLUG, [{"ref": "G-1", "fields": {"why_now": "clobber"}}], who=other)
    assert errors[0].startswith("base_rev: why_now changed by runner-sdk/draft-skill in the last 15 min")
    api.write(SLUG, [{"ref": "G-1", "base_rev": 1, "fields": {"why_now": "merged"}}], who=other)
    assert api.record(SLUG, "G-1")["rev"] == 2


def test_null_deletes_a_field_refs_must_exist_and_unknown_op_keys_are_refused(api):
    api.start()
    api.write(SLUG, [{"type": "gap", "title": "g", "fields": {**GAP, "recommendation": "a"}}])
    api.write(SLUG, [{"ref": "G-1", "fields": {"recommendation": None}}])
    assert "recommendation" not in api.record(SLUG, "G-1")["fields"]
    errors = api.rejected(SLUG, [{"ref": "G-1", "fields": {"blocks": ["D-4"]}}])
    assert errors == ["blocks[0]: D-4 does not exist in order-events"]
    r = api.agent().post(f"{api.base(SLUG)}/records", json={"ops": [{"ref": "G-1", "question": "typo"}]})
    assert r.status_code == 422 and "unknown key(s) question" in r.json()["detail"]


def test_mentions_and_history(api):
    api.start()
    api.write(SLUG, [{"type": "decision", "title": "x", "fields": {"question": "q", "domain": "engg", "level": "SHOULD"}}])
    api.write(SLUG, [{"type": "gap", "title": "g", "fields": {**GAP, "context": "Depends on D-1 and D-99."}}])
    assert {"kind": "mentions", "to": "D-1"} in api.record(SLUG, "G-1")["links"]["out"]
    assert all(link["to"] != "D-99" for link in api.record(SLUG, "G-1")["links"]["out"])
    api.write(SLUG, [{"ref": "G-1", "fields": {"why_now": "later"}, "note": "reworded"}])
    history = api.get(f"{api.base(SLUG)}/records/G-1/history")
    assert [(h["rev"], h["actor"], h["actor_kind"], h["note"]) for h in history] == [
        (2, "runner-sdk/draft-skill", "agent", "reworded"),
        (1, "runner-sdk/draft-skill", "agent", ""),
    ]


def test_global_scope_is_separate(api):
    api.start()
    agent = api.agent()
    r = agent.post("/api/global/records", json={"ops": [{"type": "learning", "fields": {"text": "Outbox rows need a TTL", "source": "order-events:F-1", "provenance": "PR review"}}]})
    assert r.status_code == 200 and r.json()["minted"] == {"#0": "L-1"}
    r = agent.post(f"{api.base(SLUG)}/records", json={"ops": [{"type": "standard", "fields": {}}]})
    assert "lives in the global scope" in r.json()["error_data"]["results"][0]["errors"][0]
    assert [x["ref"] for x in api.get("/api/learnings")] == ["L-1"]
    assert agent.post("/api/learnings/L-1/promote").status_code == 403
    api.ok(api.as_("chandra").post("/api/learnings/L-1/promote"))
    assert api.get("/api/learnings")[0]["status"] == "PROMOTED"
