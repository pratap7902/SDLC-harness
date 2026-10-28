"""deploy_guard: GO / NO-GO flips with drift and with the sha."""

from tests.fixtures.slice import SLUG, pr_open, to_task


def guard(api, sha="abc123", env="staging"):
    return api.get("/api/deploy-guard", initiative_id=api.id(SLUG), task="T-1", sha=sha, environment=env)


def test_go_needs_an_approval_at_this_sha(api):
    to_task(api)
    pr_open(api)
    out = guard(api)
    assert out["decision"] == "NO-GO"
    assert [c["name"] for c in out["checks"] if not c["passed"]] == ["GATE_PR", "approved_at_sha"]
    api.approve(SLUG, "T-1", "engg", "priya")
    assert guard(api)["decision"] == "GO"
    out = guard(api, sha="zzz")
    assert out["decision"] == "NO-GO" and out["reasons"][0].startswith("sha_matches_pr")


def test_new_drift_turns_go_into_no_go(api):
    to_task(api)
    pr_open(api)
    api.approve(SLUG, "T-1", "engg", "priya")
    assert guard(api)["decision"] == "GO"
    api.write(SLUG, [{"type": "finding", "fields": {"summary": "AC-3 wording", "severity": "nit", "target": ["AC-3"]}}])
    api.write(SLUG, [{"ref": "AC-3", "fields": {"text": "Two updates to one order share partition key order_id"}, "because": ["F-1"]}])
    out = guard(api)
    assert out["decision"] == "NO-GO" and out["drift"]["changes"] == 1


def test_post_records_a_deploy_row(api):
    to_task(api)
    pr_open(api)
    api.approve(SLUG, "T-1", "engg", "priya")
    out = api.ok(api.as_("ci", "system").post("/api/deploy-guard", json={"initiative_id": api.id(SLUG), "task": "T-1", "sha": "abc123", "environment": "production"}))
    assert out["decision"] == "GO" and out["deploy"] == "DEP-1"
    dep = api.record(SLUG, "DEP-1")
    assert dep["status"] == "PENDING" and dep["fields"]["guard_result"] == "GO"
    assert api.as_("ci").get("/api/deploy-guard", params={"initiative_id": api.id(SLUG), "task": "T-1", "sha": "x", "environment": "moon"}).status_code == 422
