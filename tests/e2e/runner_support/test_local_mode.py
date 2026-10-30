"""Service side of the runner's local mode: local repos in the registry, the pr_review item."""

from tests.fixtures.slice import SLUG, to_task


def local_repo(**extra):
    fields = {"name": "wb-be", "default_branch": "main", "local_path": "/srv/repos/wb-be", "state": "active", **extra}
    return {"ops": [{"type": "repository", "fields": fields}]}


def test_a_local_repo_by_short_name(api):
    api.ok(api.as_("priya").post("/api/global/records", json=local_repo()))
    r = api.get("/api/repos/wb-be")
    assert r["local_path"] == "/srv/repos/wb-be" and r["clone_url"] == "" and r["default_branch"] == "main"
    # local_path is executed against by the runner: a human sets it
    r = api.agent().post("/api/global/records", json=local_repo(name="other"))
    assert r.status_code == 422 and "local_path" in r.text


def test_pr_review_item_until_reviewed_at_the_head(api):
    to_task(api)
    base = api.base(SLUG)
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_state": "open", "pr_url": "local:wb-be@harness/1-T-1", "pr_sha": "abc1234"}}])
    items = api.ok(api.agent().get(f"{base}/next-work", params={"kind": "pr_review"}))["items"]
    assert [(x["key"], x["sha"]) for x in items] == [(f"pr_review:{api.id(SLUG)}:T-1", "abc1234")]
    api.write(SLUG, [{"ref": "T-1", "fields": {"reviewed_sha": "abc1234"}}])
    assert api.ok(api.agent().get(f"{base}/next-work", params={"kind": "pr_review"}))["items"] == []
    api.write(SLUG, [{"ref": "T-1", "fields": {"pr_sha": "def5678"}, "base_rev": api.record(SLUG, "T-1")["rev"]}])
    assert len(api.ok(api.agent().get(f"{base}/next-work", params={"kind": "pr_review"}))["items"]) == 1
