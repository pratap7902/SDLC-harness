"""The worker loop end to end: real service, fake agent, local bare repo as GitHub."""

from runner.tests.fakes import bare_file, bare_head
from runner.tests.helpers import (
    draft_skill,
    implement_skill,
    make_worker,
    plan_skill,
    review_draft_skill,
    revise_skill,
    run,
    write_tests_skill,
)


def to_draft_approved(srs, tmp_path) -> int:
    """draft (runner) → G-1 answered (human) → review item revised (runner) → DRI approves."""
    iid = srs.start()
    worker, agent, _ = make_worker(srs, tmp_path, {"draft-from-ticket": draft_skill, "review-draft": review_draft_skill}, kinds=["draft"])
    out = run(worker)
    # the second pass sees the submitted draft waiting on humans (G-1) and changes nothing
    assert {o["status"] for o in out} == {"done"} and out[0]["review"] == "done", out
    assert [r.skill for r in agent.runs][:2] == ["draft-from-ticket", "review-draft"]
    assert len(srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "finding"}))) == 1
    assert srs.record(iid, "draft")["fields"]["submitted_rev"] == "1"
    f1 = srs.record(iid, "F-1")
    assert f1["created_by"] == "runner-sdk/review-draft" and f1["fields"]["target"] == ["draft"]
    assert srs.record(iid, "D-1")["created_by"] == "runner-sdk/draft-from-ticket"

    srs.ok(srs.as_("maya").post(f"/api/initiatives/{iid}/gaps/G-1/answer", json={"choice": "yes", "answer": "per order"}))
    worker, agent, _ = make_worker(srs, tmp_path, {"draft-from-ticket": revise_skill, "plan-to-tasks": plan_skill}, kinds=["review"])
    out = run(worker)
    assert out and all(o["status"] == "done" for o in out), out
    srs.ok(srs.as_("chandra").post(f"/api/initiatives/{iid}/approvals", json={"target": "draft", "role": "dri"}), 201)
    return iid


def test_draft_to_pr_with_tests(srs, tmp_path, bare_repo):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(f"file://{bare_repo}")

    worker, agent, _ = make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])
    out = run(worker)
    assert out[0]["status"] == "done" and out[0]["tasks"] == ["T-1"]
    assert "REPO-1 example/orders [ACTIVE]" in agent.runs[0].notes["repos"]  # the registry over MCP

    # implement-task, then write-tests (its own lease), on the same branch
    worker, agent, gh = make_worker(srs, tmp_path, {"implement-task": implement_skill(), "write-tests": write_tests_skill}, kinds=["task", "tests"])
    out = run(worker)
    by_kind = {o["kind"]: o for o in out}
    assert by_kind["task"]["status"] == "done", out
    assert by_kind["tests"]["status"] == "done", out
    branch = f"harness/{iid}-T-1"
    head = bare_head(bare_repo, branch)
    assert bare_file(bare_repo, branch, "orders/relay.py").startswith("# relay")
    assert "test_AC_1_outbox_row" in bare_file(bare_repo, branch, "tests/test_relay.py")
    assert bare_head(bare_repo, "main") != head  # main untouched, work on the branch

    # the PR: opened once, as the App, with the task marker, drift and rollback
    assert len(gh.prs) == 1
    pr = gh.prs[1]
    assert pr["head"]["ref"] == branch and pr["base"]["ref"] == "main" and not pr["draft"]
    assert f"srs-task: {iid}/T-1" in pr["body"] and "Disable order_events.enabled" in pr["body"]

    # the records the runner guarantees
    task = srs.record(iid, "T-1")
    assert task["fields"]["pr_url"] == "https://github.com/example/orders/pull/1"
    assert task["fields"]["pr_state"] == "open" and task["fields"]["pr_sha"] == head
    assert task["status"] == "IN_REVIEW"

    # commits are the App's bot identity
    import subprocess

    author = subprocess.run(["git", "log", "-1", "--format=%an <%ae>", branch], cwd=bare_repo, capture_output=True, text=True).stdout.strip()
    assert author == "sdlc-harness-test[bot] <4242+sdlc-harness-test[bot]@users.noreply.github.com>"

    # the options the Agent SDK got
    impl = agent.runs_of("implement-task")[0]
    o = impl.options
    assert o.model == "claude-opus-5-5" and o.permission_mode == "dontAsk" and o.strict_mcp_config
    assert o.setting_sources == ["project"] and impl.notes["claude_md"]
    assert o.mcp_servers["srs"]["headers"]["Authorization"] == f"Bearer {srs.tokens['runner']}"
    assert o.mcp_servers["srs"]["url"].endswith("/mcp")
    assert "Bash(git push *)" in o.disallowed_tools and "mcp__srs__claim" in o.disallowed_tools
    assert "mcp__srs__write" in o.allowed_tools and "mcp__srs__kb_search" in o.allowed_tools
    assert "# implement-task" in o.system_prompt["append"] and o.system_prompt["preset"] == "claude_code"
    assert o.env["GIT_AUTHOR_NAME"] == "sdlc-harness-test[bot]" and not any(k.startswith("GITHUB_") for k in o.env)
    plan = [r for r in agent.runs if r.skill == "write-tests"][0].options
    assert plan.cwd != o.cwd  # each job its own clone

    # workspaces are gone, leases released
    assert not any((tmp_path / "work").iterdir())
    leases = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/worklist"))
    assert all(x["lease"] is None for x in leases["items"])


def _to_open_pr(srs, tmp_path, bare_repo, counter):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(f"file://{bare_repo}")
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])[0])
    worker, _, gh = make_worker(srs, tmp_path, {"implement-task": implement_skill(counter)}, kinds=["task"])
    run(worker)
    return iid, gh


def test_red_ci_rework_then_handoff_after_three(srs, tmp_path, bare_repo):
    counter = {}
    iid, gh = _to_open_pr(srs, tmp_path, bare_repo, counter)
    shas = []
    for attempt in (1, 2, 3):
        sha = srs.record(iid, "T-1")["fields"]["pr_sha"]
        shas.append(sha)
        srs.junit(iid, "T-1", sha, failing=True)
        items = srs.next_work("task")
        assert items and items[0]["rework"] == "ci", items
        worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill(counter)}, kinds=["task"], gh=gh)
        out = run(worker)
        task = srs.record(iid, "T-1")
        assert task["fields"]["ci_attempts"] == str(attempt)
        if attempt < 3:
            assert out[0]["status"] == "done", out
            assert task["fields"]["pr_sha"] != sha and task["fields"]["pr_sha"] == bare_head(bare_repo, f"harness/{iid}-T-1")
            assert "rework" in agent.runs[0].prompt and "ci" in agent.runs[0].prompt
        else:
            assert out[0]["status"] == "handoff" and not agent.runs  # no third agent run
    task = srs.record(iid, "T-1")
    assert task["status"] == "STUCK"
    human = [x for x in srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/worklist"))["items"] if x["kind"] == "task"]
    assert human and human[0]["lane"] == "human" and human[0]["person"] == "priya"
    assert not [x for x in srs.next_work("task") if x["lane"] == "agent"]


def test_review_findings_count_review_rounds(srs, tmp_path, bare_repo):
    counter = {}
    iid, gh = _to_open_pr(srs, tmp_path, bare_repo, counter)
    sha = srs.record(iid, "T-1")["fields"]["pr_sha"]
    srs.write(iid, [{"type": "finding", "fields": {"summary": "relay loses rows on restart", "severity": "blocker", "target": ["T-1"], "at_sha": sha}}], who="priya")
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill(counter)}, kinds=["task"], gh=gh)
    out = run(worker)
    assert out[0]["status"] == "done"
    task = srs.record(iid, "T-1")
    assert task["fields"]["review_rounds"] == "1" and task["fields"]["pr_sha"] != sha
    assert len(gh.prs) == 1  # the same PR, updated


def test_local_verification_failures_hand_off_as_draft_pr(srs, tmp_path, bare_repo):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(f"file://{bare_repo}", test_command="echo 'AC-2 relay test failed' >&2; exit 1")
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])[0])
    worker, agent, gh = make_worker(srs, tmp_path, {"implement-task": implement_skill({})}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "handoff", out
    assert len(agent.runs) == 3
    assert "AC-2 relay test failed" in agent.runs[1].prompt  # the failure is fed back
    assert gh.prs[1]["draft"] is True
    task = srs.record(iid, "T-1")
    assert task["fields"]["ci_attempts"] == "3" and task["status"] == "STUCK"


def test_unregistered_repo_raises_a_gap(srs, tmp_path):
    iid = to_draft_approved(srs, tmp_path)
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])[0])  # no repo registered: the fake still names one
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill()}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "blocked" and not agent.runs
    gaps = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "gap"}))
    gap = [g for g in gaps if "not in the registry" in g["title"]][0]
    assert gap["fields"]["blocks"] == ["T-1"] and gap["fields"]["domain"] == "engg"
    assert srs.record(iid, "T-1")["status"] == "BLOCKED"
    # retried: the same deterministic batch → no second gap
    worker, _, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill()}, kinds=["task"])
    run(worker)
    assert len([g for g in srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "gap"})) if "not in the registry" in g["title"]]) == 1


def test_agent_failure_and_crash_release_the_lease(srs, tmp_path, bare_repo):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(f"file://{bare_repo}")
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])[0])

    async def crash(ctx):
        raise RuntimeError("model process died")

    worker, agent, gh = make_worker(srs, tmp_path, {"implement-task": crash}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "agent_failed" and "model process died" in out[0]["error"]
    assert not gh.prs and bare_head(bare_repo, f"harness/{iid}-T-1") is None
    assert not any((tmp_path / "work").iterdir())
    # the lease is back: another worker (fresh, no cooldown) takes the item
    items = srs.next_work("task")
    assert items and items[0]["lease"] is None

    async def error_result(ctx):
        return "error"

    worker, _, _ = make_worker(srs, tmp_path, {"implement-task": error_result}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "agent_failed" and out[0]["error"] == "max turns"


def test_a_lease_held_by_another_runner_is_skipped(srs, tmp_path, bare_repo):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(f"file://{bare_repo}")
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill}, kinds=["plan"])[0])
    srs.ok(srs.as_("ci").post("/api/leases/claim", json={"item_key": f"task:{iid}:T-1", "ttl_min": 5}))
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill()}, kinds=["task"])
    assert run(worker) == [] and not agent.runs
