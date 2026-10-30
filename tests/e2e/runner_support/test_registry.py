"""The repo registry: global `repository` records, REST + MCP reads, human-only test_command."""

from app.mcp import server as mcp_server

REPO = {
    "type": "repository",
    "fields": {
        "name": "example/orders",
        "default_branch": "main",
        "test_command": "pytest -q --junitxml=reports/junit.xml",
        "junit_path": "reports/junit.xml",
        "templates": ["python-service", "helm-worker"],
        "owners": ["priya"],
        "state": "active",
    },
}


def register(api, who=None, **fields):
    op = {"type": "repository", "fields": {**REPO["fields"], **fields}}
    return (who or api.as_("priya")).post("/api/global/records", json={"ops": [op]})


def test_human_registers_and_everyone_reads(api):
    api.ok(register(api))
    repos = api.get("/api/repos")
    assert [r["name"] for r in repos] == ["example/orders"]
    r = api.get("/api/repos/example/orders")
    assert r["ref"] == "REPO-1" and r["status"] == "ACTIVE" and r["default_branch"] == "main"
    assert r["clone_url"] == "https://github.com/example/orders.git"
    assert r["templates"] == ["python-service", "helm-worker"] and r["test_command"].startswith("pytest")
    assert api.as_("x").get("/api/repos/example/nope").status_code == 404


def test_agents_cannot_set_the_test_command(api):
    r = register(api, who=api.agent())
    assert r.status_code == 422 and "test_command" in r.text
    fields = dict(REPO["fields"])
    fields.pop("test_command")
    api.ok(api.agent().post("/api/global/records", json={"ops": [{"type": "repository", "fields": fields}]}))
    assert api.get("/api/repos/example/orders")["test_command"] == ""


def test_retired_repos_are_hidden(api):
    api.ok(register(api))
    api.ok(api.as_("priya").post("/api/global/records", json={"ops": [{"ref": "REPO-1", "fields": {"state": "retired"}}]}))
    assert api.get("/api/repos") == []
    assert len(api.get("/api/repos", include_retired="true")) == 1


def test_mcp_repos_tool(api):
    assert "no repositories" in mcp_server.repos()
    api.ok(register(api))
    text = mcp_server.repos()
    assert "REPO-1 example/orders [ACTIVE] branch main" in text and "python-service" in text
    assert "junit reports/junit.xml" in mcp_server.repos("example/orders")
