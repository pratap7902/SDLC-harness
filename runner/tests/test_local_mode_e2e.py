"""Local mode (the default): a repository on this machine, a sandbox clone, a branch that is
never pushed, review-pr through the Agent SDK on the branch diff — and no GitHub anywhere."""

import subprocess
import sys

from runner.local_workspace import NO_PUSH, sandbox_path
from runner.tests.conftest import ROOT, git
from runner.tests.helpers import implement_skill, make_worker, plan_skill_for, review_pr_skill, run, write_tests_skill
from runner.tests.test_worker_e2e import to_draft_approved


def _planned(srs, tmp_path, local_repo, test_command="sh check.sh") -> int:
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(name="wb-be", local_path=str(local_repo), test_command=test_command)
    out = run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill_for("wb-be")}, kinds=["plan"])[0])
    assert out[0]["tasks"] == ["T-1"], out
    return iid


def sandbox_git(tmp_path, *args):
    return git(*args, cwd=sandbox_path(tmp_path / "work", "wb-be"))


def test_local_task_tests_review_and_approval(srs, tmp_path, local_repo):
    iid = _planned(srs, tmp_path, local_repo)
    src_head = git("rev-parse", "HEAD", cwd=local_repo)
    worker, agent, gh = make_worker(
        srs, tmp_path, {"implement-task": implement_skill(), "write-tests": write_tests_skill, "review-pr": review_pr_skill}, kinds=["task", "tests", "pr_review"]
    )
    assert gh is None and worker.github is None  # no GitHub object in local mode
    out = run(worker)
    by_kind = {o["kind"]: o for o in out}
    assert by_kind["task"]["status"] == "done" and by_kind["tests"]["status"] == "done" and by_kind["pr_review"]["status"] == "done", out

    branch = f"harness/{iid}-T-1"
    head = sandbox_git(tmp_path, "rev-parse", f"refs/heads/{branch}")
    # the "PR" is the sandbox branch + its head sha
    task = srs.record(iid, "T-1")
    assert task["fields"]["pr_url"] == f"local:wb-be@{branch}"
    assert task["fields"]["pr_state"] == "open" and task["fields"]["pr_sha"] == head
    assert task["fields"]["reviewed_sha"] == head and task["status"] == "IN_REVIEW"
    assert "orders/relay.py" in sandbox_git(tmp_path, "diff", "--name-only", f"main...{branch}")
    assert "tests/test_relay.py" in sandbox_git(tmp_path, "diff", "--name-only", f"main...{branch}")

    # the developer's repository is untouched: no branch, same head, clean
    assert git("rev-parse", "HEAD", cwd=local_repo) == src_head
    assert git("branch", "--list", "harness/*", cwd=local_repo) == ""
    assert git("status", "--porcelain", cwd=local_repo) == ""

    # pushing is impossible from the sandbox
    assert sandbox_git(tmp_path, "remote", "get-url", "--push", "origin") == NO_PUSH
    p = subprocess.run(["git", "push", "origin", branch], cwd=sandbox_path(tmp_path / "work", "wb-be"), capture_output=True, text=True)
    assert p.returncode != 0

    # local evidence: the runner ran check.sh at the head and posted its JUnit, bound to that sha
    runs = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "test_run"}))
    at_head = [r for r in runs if r["fields"]["at_sha"] == head]
    assert at_head and at_head[0]["status"] == "GREEN" and at_head[0]["fields"]["run_url"] == f"local:wb-be@{head}"
    assert {row["ac"] for row in at_head[0]["fields"]["covers"]} == {"AC-1", "AC-2", "AC-3"}
    assert "reports/junit.xml" not in sandbox_git(tmp_path, "ls-tree", "-r", "--name-only", branch)  # never committed

    # review-pr ran through the Agent SDK on the branch diff, and filed its finding at the head
    review = agent.runs_of("review-pr")[0]
    assert f"git diff main...{branch}" in review.prompt and "relay" in review.notes["diff"]
    assert "Bash(git diff *)" in review.options.allowed_tools and "Bash(gh *)" in review.options.disallowed_tools
    f1 = [f for f in srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "finding"})) if f["created_by"] == "runner-sdk/review-pr"][0]
    assert f1["fields"]["at_sha"] == head
    impl = agent.runs_of("implement-task")[0]
    assert "NO remote to push to" in impl.prompt and impl.notes["claude_md"]

    # a human approves that sha in the harness: GATE_PR passes
    srs.ok(srs.as_("priya").post(f"/api/initiatives/{iid}/approvals", json={"target": "T-1", "role": "engg", "at_sha": head}), 201)
    gate = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/tasks/T-1/gates"))[0]
    assert gate["status"] == "PASSED", gate
    assert not [x for x in srs.next_work("pr_review")]  # reviewed at this sha

    # workspaces gone (the sandbox stays), leases released
    assert [p.name for p in (tmp_path / "work").iterdir()] == ["sandboxes"]
    assert sandbox_git(tmp_path, "worktree", "list").count("\n") == 0  # only the bare sandbox itself


def test_local_rework_continues_the_branch(srs, tmp_path, local_repo):
    iid = _planned(srs, tmp_path, local_repo)
    counter = {}
    run(make_worker(srs, tmp_path, {"implement-task": implement_skill(counter)}, kinds=["task"])[0])
    sha1 = srs.record(iid, "T-1")["fields"]["pr_sha"]
    srs.junit(iid, "T-1", sha1, failing=True)  # e.g. a human ran a slower suite and posted it
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill(counter)}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "done", out
    task = srs.record(iid, "T-1")
    assert task["fields"]["ci_attempts"] == "1" and task["fields"]["pr_sha"] != sha1
    branch = f"harness/{iid}-T-1"
    assert sandbox_git(tmp_path, "rev-list", "--count", f"main..{branch}") == "2"  # continued, not restarted
    assert "round 2" in sandbox_git(tmp_path, "show", f"{branch}:orders/relay.py")


def test_local_verification_failures_hand_off(srs, tmp_path, local_repo):
    iid = _planned(srs, tmp_path, local_repo, test_command="exit 1")
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill({})}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "handoff" and len(agent.runs) == 3
    task = srs.record(iid, "T-1")
    assert task["fields"]["pr_state"] == "draft" and task["fields"]["ci_attempts"] == "3" and task["status"] == "STUCK"


def test_missing_local_path_raises_a_gap(srs, tmp_path):
    iid = to_draft_approved(srs, tmp_path)
    srs.register_repo(name="wb-be")  # no local_path
    run(make_worker(srs, tmp_path, {"plan-to-tasks": plan_skill_for("wb-be")}, kinds=["plan"])[0])
    worker, agent, _ = make_worker(srs, tmp_path, {"implement-task": implement_skill()}, kinds=["task"])
    out = run(worker)
    assert out[0]["status"] == "blocked" and not agent.runs
    gaps = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/records", params={"type": "gap"}))
    assert any("no local_path" in g["title"] for g in gaps)


def test_heartbeat_extends_the_lease_while_the_skill_runs(srs, tmp_path):
    import asyncio

    iid = to_draft_approved(srs, tmp_path)
    seen = []

    async def slow_plan(ctx):
        for _ in range(3):
            items = srs.ok(srs.as_("chandra").get(f"/api/initiatives/{iid}/worklist"))["items"]
            seen.append(next(x["lease"]["expires_at"] for x in items if x["kind"] == "plan"))
            await asyncio.sleep(1.2)

    worker, _, _ = make_worker(srs, tmp_path, {"plan-to-tasks": slow_plan}, kinds=["plan"], heartbeat_s=1.0)
    run(worker)
    assert len(set(seen)) >= 2, seen  # the expiry moved forward: heartbeats landed


def test_local_mode_imports_no_github_code():
    code = (
        "import sys\n"
        "from runner.config import Settings\n"
        "from runner.worker import Worker\n"
        "from runner import local_workspace\n"
        "w = Worker(Settings(srs_token='t'), skills={})\n"
        "assert w.github is None\n"
        "bad = [m for m in sys.modules if m in ('runner.github_app', 'jwt') or m.startswith('jwt.')]\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip() == "ok", p.stderr
