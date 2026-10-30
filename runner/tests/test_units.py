"""GitHub App auth, the workspace's git handling, skills, settings, docker mode."""

import asyncio
import json
import subprocess
from pathlib import Path

import jwt
import pytest

from runner import agent as agent_mod
from runner.config import Settings
from runner.github_app import GithubApp, app_jwt
from runner.skills import POLICIES, load_all, skill_for
from runner.tests.conftest import git
from runner.tests.fakes import FakeGithub, bare_file, bare_head
from runner.tests.helpers import PRIVATE_PEM, PUBLIC_PEM, ROOT
from runner.workspace import Workspace, auth_env, branch_name

# ── GitHub App ───────────────────────────────────────────────────────────────


def test_app_jwt_claims():
    token = app_jwt("12345", PRIVATE_PEM, now=1_800_000_000)
    claims = jwt.decode(token, PUBLIC_PEM, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims == {"iat": 1_800_000_000 - 60, "exp": 1_800_000_000 + 540, "iss": "12345"}


def test_installation_token_is_scoped_and_cached():
    gh = FakeGithub()
    app = GithubApp("12345", PRIVATE_PEM, "https://api.github.test", "777", "bot", transport=gh.transport())

    async def go():
        a = await app.token("example/orders")
        b = await app.token("example/orders")
        await app.aclose()
        return a, b

    a, b = asyncio.run(go())
    assert a == b == "ghs_fake1" and gh.tokens_issued == 1
    req = gh.requests[0]
    assert req.url.path == "/app/installations/777/access_tokens"
    body = json.loads(req.content)
    assert body["repositories"] == ["orders"] and body["permissions"]["contents"] == "write"


def test_open_or_update_pr_is_idempotent():
    gh = FakeGithub()
    app = GithubApp("12345", PRIVATE_PEM, "https://api.github.test", "777", "bot", transport=gh.transport())

    async def go():
        one = await app.open_or_update_pr("example/orders", "harness/1-T-1", "main", "T-1: x", "body 1")
        two = await app.open_or_update_pr("example/orders", "harness/1-T-1", "main", "T-1: x", "body 2")
        await app.aclose()
        return one, two

    one, two = asyncio.run(go())
    assert one.number == two.number == 1 and len(gh.prs) == 1 and gh.prs[1]["body"] == "body 2"


# ── workspace ────────────────────────────────────────────────────────────────


def _ws(tmp_path, bare, name="w1", token="ghs_secret_token_value"):
    return Workspace(
        root=tmp_path / name,
        repo="example/orders",
        clone_url=f"file://{bare}",
        default_branch="main",
        branch=branch_name("harness/", 3, "T-1"),
        author_name="bot[bot]",
        author_email="1+bot[bot]@users.noreply.github.com",
        token=token,
    )


def test_token_never_reaches_disk(tmp_path, bare_repo):
    ws = _ws(tmp_path, bare_repo).prepare()
    config = (ws.path / ".git" / "config").read_text()
    assert "ghs_secret_token_value" not in config and "extraheader" not in config.lower()
    assert git("remote", "get-url", "origin", cwd=ws.path) == f"file://{bare_repo}"
    env = auth_env("ghs_secret_token_value")
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader" and "ghs_secret_token_value" not in env["GIT_CONFIG_VALUE_0"]  # base64
    ws.cleanup()
    assert not ws.root.exists()


def test_branch_continues_and_push_rebases_over_a_concurrent_push(tmp_path, bare_repo):
    a = _ws(tmp_path, bare_repo, "a").prepare()
    b = _ws(tmp_path, bare_repo, "b").prepare()
    assert not a.branch_existed
    (a.path / "impl.py").write_text("x = 1\n")
    assert a.commit_all("T-1: impl")
    a.push()
    (b.path / "test_ac.py").write_text("def test_AC_1(): pass\n")
    assert b.commit_all("T-1: tests")
    sha = b.push()  # non-fast-forward → fetch + rebase → push
    assert bare_head(bare_repo, "harness/3-T-1") == sha
    assert bare_file(bare_repo, "harness/3-T-1", "impl.py") and bare_file(bare_repo, "harness/3-T-1", "test_ac.py")
    c = _ws(tmp_path, bare_repo, "c").prepare()
    assert c.branch_existed and (c.path / "impl.py").exists() and not c.commit_all("nothing")
    log = subprocess.run(["git", "log", "-1", "--format=%an", "harness/3-T-1"], cwd=bare_repo, capture_output=True, text=True).stdout.strip()
    assert log == "bot[bot]"


# ── skills ───────────────────────────────────────────────────────────────────


def test_every_skill_loads_and_has_a_policy():
    skills = load_all(ROOT / "skills")
    assert set(skills) == set(POLICIES) == {"draft-from-ticket", "review-draft", "plan-to-tasks", "implement-task", "write-tests", "review-pr", "harvest-learnings"}
    for s in skills.values():
        assert s.description and len(s.body) > 500
        assert "KB-TODO" not in s.body and "records.write" not in s.body  # the real tools, no placeholders
        assert "mcp__srs__claim" in s.policy.disallowed
    body = skills["draft-from-ticket"].body
    assert "kb:outline/" in body and "because" in body and "provisional" in body.lower()
    assert "never from the implementation" in skills["write-tests"].description


def test_tool_policies():
    assert "Bash" not in POLICIES["draft-from-ticket"].allowed and "Bash" in POLICIES["draft-from-ticket"].disallowed
    assert "Bash" in POLICIES["implement-task"].allowed and "Bash(git push *)" in POLICIES["implement-task"].disallowed
    assert POLICIES["implement-task"].load_project_settings and not POLICIES["plan-to-tasks"].load_project_settings


def test_skill_for_kinds():
    assert skill_for({"kind": "draft"}) == "draft-from-ticket"
    assert skill_for({"kind": "review", "context": {"record": {"type": "task"}}}) == "plan-to-tasks"
    assert skill_for({"kind": "review", "context": {"record": {"type": "decision"}}}) == "draft-from-ticket"
    with pytest.raises(KeyError):
        skill_for({"kind": "approval"})


# ── settings, docker ─────────────────────────────────────────────────────────


def test_settings_from_env(tmp_path):
    key = tmp_path / "app.pem"
    key.write_text(PRIVATE_PEM)
    s = Settings.from_env({"SRS_URL": "https://srs.example.com/", "SRS_TOKEN": "t", "RUNNER_KINDS": "task,tests", "GITHUB_APP_ID": "9", "GITHUB_APP_PRIVATE_KEY_PATH": str(key), "RUNNER_MAX_BUDGET_USD": "3.5"})
    assert s.srs_url == "https://srs.example.com" and s.kinds == ["task", "tests"] and s.github_private_key == PRIVATE_PEM
    assert s.model == "claude-opus-5-5" and s.max_budget_usd == 3.5
    with pytest.raises(ValueError):
        Settings.from_env({"RUNNER_EXECUTION_MODE": "k8s"})


def test_docker_command_carries_no_github_secret(tmp_path):
    s = Settings(docker_image="sdlc-harness-runner:test", github_private_key=PRIVATE_PEM, workspace_mode="github")
    cmd = agent_mod.docker_command(s, tmp_path)
    joined = " ".join(cmd)
    assert cmd[:3] == ["docker", "run", "--rm"] and f"{tmp_path}:/job" in joined
    assert cmd[-3:] == ["sdlc-harness-runner:test", "exec-job", "/job/job.json"]
    assert "GITHUB" not in joined and "PRIVATE" not in joined
    assert "-e" in cmd and "ANTHROPIC_API_KEY" in cmd and "SRS_TOKEN" in cmd


def test_options_for_a_records_only_skill(tmp_path):
    s = Settings(srs_url="https://srs.example.com", srs_token="tok", extra_mcp_json=json.dumps({"other": {"type": "http", "url": "https://x.example.com/mcp"}}))
    skill = load_all(ROOT / "skills")["plan-to-tasks"]
    o = agent_mod.build_options(s, skill, Path(tmp_path))
    assert o.setting_sources == [] and o.max_turns == 50 and o.cwd == str(tmp_path)
    assert set(o.mcp_servers) == {"srs", "other"} and o.mcp_servers["srs"]["url"] == "https://srs.example.com/mcp"
    assert "Bash" in o.disallowed_tools


def test_cli_path_passes_through_and_defaults_to_bundled(tmp_path):
    skill = load_all(ROOT / "skills")["plan-to-tasks"]
    assert agent_mod.build_options(Settings(), skill, tmp_path).cli_path is None  # bundled CLI
    s = Settings.from_env({"CLAUDE_CLI_PATH": "/opt/claude/bin/claude"})
    assert agent_mod.build_options(s, skill, tmp_path).cli_path == "/opt/claude/bin/claude"
    assert any("CLAUDE_CLI_PATH" in p for p in s.problems())  # it does not exist here
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    fake.chmod(0o755)
    info = agent_mod.cli_info(Settings(cli_path=str(fake)))
    assert info == {"cli_path": str(fake), "cli_source": "CLAUDE_CLI_PATH", "cli_version": "9.9.9 (Claude Code)"}


def test_auth_is_api_key_or_a_cloud_provider_never_a_login(monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS"):
        monkeypatch.delenv(v, raising=False)
    assert Settings.api_auth() == ""
    assert any("never a claude.ai login" in p for p in Settings().problems())
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    assert Settings.api_auth() == "CLAUDE_CODE_USE_BEDROCK"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert Settings.api_auth() == "ANTHROPIC_API_KEY"


def test_docker_local_mode_mounts_the_work_root_at_the_same_path(tmp_path):
    s = Settings(docker_image="img", work_root=tmp_path)
    job = tmp_path / "1-T-1-x"
    (job / "repo").mkdir(parents=True)
    cmd = agent_mod.docker_command(s, job)
    assert f"{tmp_path}:{tmp_path}" in cmd and cmd[cmd.index("-w") + 1] == str(job / "repo")
    assert cmd[-1] == str(job / "job.json")
