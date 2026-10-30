"""The worker loop.

    poll next_work (the kinds this runner serves, agent lane only)
      → claim the lease (409 = someone else has it: skip)
      → heartbeat it in the background (every RUNNER_HEARTBEAT_S)
      → prepare a workspace: local mode (default) a worktree of a sandbox clone of the
        registered local_path; GitHub mode a clone as the App; or a scratch dir
      → run the skill with the Agent SDK
      → make sure the records exist (pr_url / pr_state / pr_sha, attempt counters):
        local mode records `local:<repo>@<branch>` + head sha and never pushes
      → release the lease, delete the workspace (always, in `finally`)

Crash safety: every write the runner makes has a deterministic batch_id (a retry replays,
never doubles); a dead runner's lease expires on read and another runner picks the item up;
PR creation looks for the branch's open PR first; branches are pushed, never force-pushed.

Handoff (blueprint/lifecycle.yaml `handoff:`): a failed local verification or a red CI run at
the PR head counts a CI attempt (`task.ci_attempts`); a rework round for review findings
counts `task.review_rounds`. At 3 the task derives STUCK and goes to the human lane — the
runner stops working it (it pushes what it has as a draft PR so the human can see it)."""

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from runner import agent as agent_mod
from runner.agent import AgentResult, QueryFn
from runner.config import Settings
from runner.log import log
from runner.skills import Skill, load_all, skill_for
from runner.srs_client import SrsClient, SrsError, batch_id
from runner.workspace import Scratch, Workspace, branch_name, run_command

CONTEXT_CHARS = 40_000
IDLE_COOLDOWN_S = 1800  # an item handled in this state is not retaken for 30 minutes


def _tail(text: str, n: int = 4000) -> str:
    return text if len(text) <= n else "…" + text[-n:]


class Worker:
    def __init__(
        self,
        settings: Settings,
        srs: Optional[SrsClient] = None,
        github=None,  # a runner.github_app.GithubApp (GitHub mode only)
        query_fn: Optional[QueryFn] = None,
        skills: Optional[Dict[str, Skill]] = None,
    ):
        self.settings = settings
        self.srs = srs or SrsClient(settings.srs_url, settings.srs_token)
        self.github = github
        if self.github is None and settings.workspace_mode == "github":
            # imported only in GitHub mode: local mode has no GitHub code path at all
            from runner.github_app import GithubApp

            if not (settings.github_app_id and settings.github_private_key):
                raise ValueError("WORKSPACE_MODE=github needs GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY(_PATH)")
            self.github = GithubApp(
                settings.github_app_id,
                settings.github_private_key,
                settings.github_api_url,
                settings.github_installation_id,
                settings.github_app_slug,
                settings.github_bot_user_id,
            )
        self.query_fn = query_fn
        self.skills = skills or load_all(settings.skills_dir)
        self.sem = asyncio.Semaphore(max(1, settings.concurrency))
        self.in_flight: Set[str] = set()
        self.idle_until: Dict[str, float] = {}
        self.tasks: Set[asyncio.Task] = set()
        self.locks: Dict[str, asyncio.Lock] = {}
        self.outcomes: List[dict] = []  # what each job ended as (tests and `once` read it)

    # ── the loop ─────────────────────────────────────────────────────────

    async def run_forever(self, stop: asyncio.Event) -> None:
        log.info("runner_started", kinds=self.settings.kinds, concurrency=self.settings.concurrency, model=self.settings.model, workspace=self.settings.workspace_mode, mode=self.settings.execution_mode, auth=Settings.api_auth() or "none", **agent_mod.cli_info(self.settings))
        while not stop.is_set():
            try:
                await self.poll_once()
            except Exception as e:  # noqa: BLE001 — the service may be down; try again
                log.error("poll_failed", error=str(e)[:300])
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.poll_interval_s)
            except asyncio.TimeoutError:
                pass
        log.info("runner_stopping", in_flight=sorted(self.in_flight))
        await self.drain()

    async def drain(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def run_until_idle(self, max_rounds: int = 20) -> List[dict]:
        """Poll and finish everything there is (tests, `python -m runner once`)."""
        for _ in range(max_rounds):
            started = await self.poll_once()
            await self.drain()
            if not started:
                break
        return self.outcomes

    async def poll_once(self) -> int:
        started = 0
        now = time.time()
        for kind in self.settings.kinds:
            free = self.settings.concurrency - len(self.in_flight)
            if free <= 0:
                break
            for item in await self.srs.next_work(kind, limit=max(5, free * 2)):
                if len(self.in_flight) >= self.settings.concurrency:
                    break
                key = item["key"]
                if item.get("lane") != "agent" or key in self.in_flight or self.idle_until.get(self._sig(item), 0) > now:
                    continue
                lease = await self.srs.claim(key, self.settings.lease_ttl_min)
                if lease is None:
                    log.debug("lease_taken", key=key)
                    continue
                log.info("claimed", key=key, kind=kind, initiative=item.get("initiative_id"), ref=item.get("ref"), why=item.get("why"))
                self.in_flight.add(key)
                task = asyncio.create_task(self._job(item))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
                started += 1
        return started

    async def _job(self, item: dict) -> None:
        key = item["key"]
        hb = asyncio.create_task(self._heartbeat(key))
        outcome = {"key": key, "kind": item.get("kind"), "status": "error"}
        try:
            async with self.sem:
                handler = getattr(self, f"_do_{item['kind']}")
                outcome.update(await handler(item) or {})
        except Exception as e:  # noqa: BLE001
            log.error("job_failed", key=key, error=str(e)[:500], exc=True)
            outcome["error"] = str(e)[:500]
        finally:
            hb.cancel()
            try:
                await self.srs.release(key)
            except Exception as e:  # noqa: BLE001 — it expires anyway
                log.warning("release_failed", key=key, error=str(e)[:200])
            self.in_flight.discard(key)
            # the same item in the same state is not taken again by this process for a while
            # (a draft waiting on humans, tests waiting on CI); a changed `why` is new work
            self.idle_until[self._sig(item)] = time.time() + IDLE_COOLDOWN_S
            self.outcomes.append(outcome)
            log.info("released", **outcome)

    @staticmethod
    def _sig(item: dict) -> str:
        return f"{item['key']}|{item.get('why')}|{item.get('rework')}|{','.join(item.get('rework_refs') or [])}"

    async def _heartbeat(self, key: str) -> None:
        while True:
            await asyncio.sleep(self.settings.heartbeat_s)
            try:
                await self.srs.heartbeat(key, self.settings.lease_ttl_min)
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat_failed", key=key, error=str(e)[:200])

    # ── running a skill ──────────────────────────────────────────────────

    async def _run(self, skill_name: str, prompt: str, cwd: Path, job_dir: Path, env: Optional[Dict[str, str]] = None) -> AgentResult:
        skill = self.skills[skill_name]
        if self.settings.execution_mode == "docker":
            return await agent_mod.run_in_docker(self.settings, skill, prompt, job_dir, env)
        return await agent_mod.run_skill(self.settings, skill, prompt, cwd, env, self.query_fn)

    def _prompt(self, item: dict, skill: str, extra: str = "") -> str:
        context = json.dumps(item.get("context") or {}, indent=1, default=str)
        if len(context) > CONTEXT_CHARS:
            context = context[:CONTEXT_CHARS] + "\n… (truncated: read_record for the rest)"
        head = {k: item.get(k) for k in ("key", "kind", "initiative_id", "initiative", "ref", "title", "why", "rework", "rework_refs") if item.get(k) is not None}
        return (
            f"Run the `{skill}` skill for this work item.\n\n## Work item\n```json\n{json.dumps(head, indent=1)}\n```\n\n"
            f"## Context bundle (next_work)\n```json\n{context}\n```\n"
            + (f"\n{extra.strip()}\n" if extra else "")
            + f"\nWrite through the `srs` MCP tools with agent: \"{skill}\" and a batch_id that starts with "
            f"\"{item['key']}:\". Finish with a three-line summary: what you wrote (refs), what you "
            "raised for a human (refs), what is left."
        )

    # ── handlers: record-only skills ─────────────────────────────────────

    async def _scratch_skill(self, item: dict, skill: str, extra: str = "") -> AgentResult:
        scratch = Scratch(self.settings.work_root, item["key"])
        try:
            return await self._run(skill, self._prompt(item, skill, extra), scratch.path, scratch.path)
        finally:
            scratch.cleanup()

    async def _do_draft(self, item: dict) -> dict:
        iid = item["initiative_id"]
        res = await self._scratch_skill(item, "draft-from-ticket")
        if not res.ok:
            return {"status": "agent_failed", "error": res.error}
        try:
            draft = await self.srs.record(iid, "draft")
        except SrsError:
            log.warning("no_records", key=item["key"], expected="draft")
            return {"status": "no_changes"}
        out = {"status": "done", "draft_rev": draft.get("rev")}
        if (draft.get("fields") or {}).get("submitted_rev"):
            review_item = {**item, "why": f"draft submitted at rev {draft['fields']['submitted_rev']} — first-pass review before the DRI"}
            r2 = await self._scratch_skill(review_item, "review-draft")
            out["review"] = "done" if r2.ok else f"failed: {r2.error[:200]}"
        return out

    async def _do_review(self, item: dict) -> dict:
        res = await self._scratch_skill(item, skill_for(item))
        return {"status": "done" if res.ok else "agent_failed", "error": res.error or None}

    async def _do_plan(self, item: dict) -> dict:
        res = await self._scratch_skill(item, "plan-to-tasks")
        if not res.ok:
            return {"status": "agent_failed", "error": res.error}
        tasks = await self.srs.records(item["initiative_id"], "task")
        return {"status": "done" if tasks else "no_changes", "tasks": [t["ref"] for t in tasks]}

    async def harvest(self) -> dict:
        """Scheduled (weekly): harvest-learnings over every initiative, under lease harvest:0."""
        key = "harvest:0"
        if await self.srs.claim(key, self.settings.lease_ttl_min) is None:
            return {"status": "leased"}
        item = {"key": key, "kind": "harvest", "initiative_id": 0, "why": "weekly harvest of review outcomes into draft learnings"}
        hb = asyncio.create_task(self._heartbeat(key))
        try:
            res = await self._scratch_skill(item, "harvest-learnings")
            return {"status": "done" if res.ok else "agent_failed", "error": res.error or None}
        finally:
            hb.cancel()
            await self.srs.release(key)

    # ── handlers: repo skills ────────────────────────────────────────────

    @property
    def local(self) -> bool:
        return self.settings.workspace_mode == "local"

    async def _repo_or_gap(self, item: dict, task: dict, skill: str) -> Optional[dict]:
        name = (task.get("fields") or {}).get("repo") or ""
        repo = await self.srs.repo(name) if name else None
        missing = ""
        if repo is None or repo.get("status") == "RETIRED":
            missing = "is not in the registry"
        elif self.local and not repo.get("local_path"):
            missing = "has no local_path registered (local mode)"
        if not missing:
            return repo
        iid, ref = item["initiative_id"], item["ref"]
        gap = {
            "type": "gap",
            "title": f"Repository {name or '(none)'} {missing}",
            "fields": {
                "question": f"{ref} names repo `{name or '—'}`, which {missing}. Register it (base branch, {'local_path, ' if self.local else ''}test command, JUnit path, templates) or re-plan {ref}?",
                "kind": "unknown",
                "domain": "engg",
                "asked_by": f"{self.settings.principal}/{skill}",
                "why_now": f"The runner cannot check out or verify {ref} without a registry entry",
                "context": f"Task {ref} ({task.get('title')}) has `repo: {name or '—'}`. GET /api/repos lists what is registered; a human adds or edits a `repository` record (local_path and test_command are human-only).",
                "blocks": [ref],
            },
        }
        await self.srs.write(iid, [gap], batch_id(item["key"], "repo-missing", name, missing), skill)
        log.warning("repo_not_ready", key=item["key"], repo=name, reason=missing)
        return None

    def _branch_lock(self, repo: str, branch: str) -> asyncio.Lock:
        """git allows a branch in one worktree at a time: jobs on one branch take turns."""
        return self.locks.setdefault(f"{repo}@{branch}", asyncio.Lock())

    async def _workspace(self, repo: dict, iid: int, ref: str):
        name = repo["name"]
        branch = branch_name(self.settings.branch_prefix, iid, ref)
        self.settings.work_root.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix=f"{iid}-{ref}-", dir=self.settings.work_root))
        if self.local:
            from runner.local_workspace import LocalWorkspace, ensure_sandbox

            async with self.locks.setdefault(f"sandbox:{name}", asyncio.Lock()):
                sandbox = await asyncio.to_thread(ensure_sandbox, self.settings.work_root, name, repo["local_path"], repo["default_branch"])
            ws = LocalWorkspace(root=root, repo=name, sandbox=sandbox, default_branch=repo["default_branch"], branch=branch)
        else:
            token = await self.github.token(name)
            author = await self.github.bot_identity(name)
            ws = Workspace(
                root=root,
                repo=name,
                clone_url=repo["clone_url"],
                default_branch=repo["default_branch"],
                branch=branch,
                author_name=author[0],
                author_email=author[1],
                token=token,
            )
        try:
            await asyncio.to_thread(ws.prepare)
            if repo.get("junit_path"):
                ws.exclude(repo["junit_path"])
        except Exception:
            ws.cleanup()
            raise
        return ws

    async def _count(self, iid: int, ref: str, field: str, task: dict, seed: str, skill: str, note: str) -> int:
        n = int((task.get("fields") or {}).get(field) or 0) + 1
        await self.srs.update(iid, ref, {field: str(n)}, seed, skill, note)
        return n

    async def _pr_body(self, iid: int, task: dict, skill: str) -> str:
        f = task.get("fields") or {}
        ref = task["ref"]
        drift = await self.srs.drift_markdown(iid, ref)
        drift_lines = drift.splitlines()[:40]
        lines = [
            f"**{ref}** — {f.get('goal') or task.get('title')}",
            "",
            f"- Task: {self.settings.srs_url}/features/{iid}/tasks/{ref}",
            f"- Implements: {', '.join(f.get('implements') or []) or '—'} · Covers: {', '.join(f.get('covers') or []) or '—'}",
            f"- Template: {f.get('template') or '—'}",
            "",
            "**Rollback**",
            "",
            f.get("rollback") or "_none written — the reviewer should ask_",
            "",
            "**Drift since the approved baseline** (what the engg reviewer approves)",
            "",
            *(drift_lines or ["_no baseline drift report available_"]),
            "",
            f"<sub>Opened by the SDLC harness runner ({skill}, {self.settings.model}). srs-task: {iid}/{ref}</sub>",
        ]
        return "\n".join(lines)

    async def _record(self, iid: int, ref: str, url: str, state: str, sha: str, skill: str, key: str, note: str) -> None:
        await self.srs.update(iid, ref, {"pr_url": url, "pr_state": state, "pr_sha": sha}, f"{key}:pr:{state}:{sha}", skill, note)

    async def _publish(self, ws, iid: int, task: dict, skill: str, key: str, draft: bool) -> dict:
        """Make the work visible as the task's "PR". Local: the sandbox branch and its head
        (`local:<repo>@<branch>`), never pushed. GitHub: push, open/update the PR."""
        ref = task["ref"]
        if self.local:
            sha = ws.head()
            await self._record(iid, ref, ws.pr_url, "draft" if draft else "open", sha, skill, key, f"{ws.pr_url} at {sha[:7]}")
            return {"sha": sha, "pr": ws.pr_url}
        sha = await asyncio.to_thread(ws.push)
        pr = await self.github.open_or_update_pr(ws.repo, ws.branch, ws.default_branch, f"{ref}: {task.get('title')}", await self._pr_body(iid, task, skill), draft=draft)
        await self._record(iid, ref, pr.html_url, pr.pr_state, sha, skill, key, f"PR #{pr.number} at {sha[:7]}")
        return {"sha": sha, "pr": pr.html_url}

    async def _do_task(self, item: dict) -> dict:
        skill = "implement-task"
        iid, ref, key = item["initiative_id"], item["ref"], item["key"]
        task = await self.srs.record(iid, ref)
        rework = item.get("rework")
        if rework:
            field, limit = ("ci_attempts", self.settings.max_ci_attempts) if rework == "ci" else ("review_rounds", self.settings.max_review_rounds)
            n = await self._count(iid, ref, field, task, f"{key}:{rework}:{task['fields'].get('pr_sha')}", skill, f"rework ({rework}): {', '.join(item.get('rework_refs') or [])}")
            if n >= limit:
                log.warning("handoff", key=key, reason=f"{field}={n}", limit=limit)
                return {"status": "handoff", "reason": f"{field}={n}"}
            task = await self.srs.record(iid, ref)
        repo = await self._repo_or_gap(item, task, skill)
        if repo is None:
            return {"status": "blocked", "reason": "repo not ready"}
        branch = branch_name(self.settings.branch_prefix, iid, ref)
        async with self._branch_lock(repo["name"], branch):
            ws = await self._workspace(repo, iid, ref)
            try:
                if self.local and (task.get("fields") or {}).get("pr_state") not in ("draft", "open", "approved"):
                    # local "PR" lifecycle: draft while the agent works, open when it is done
                    await self._record(iid, ref, ws.pr_url, "draft", ws.head(), skill, key, f"{ws.pr_url}: work started")
                failure = ""
                draft_pr = False
                while True:
                    extra = self._repo_brief(ws, repo, item)
                    if failure:
                        extra += f"\n## The last local verification failed\n`{repo['test_command']}`:\n```\n{failure}\n```\nFix it."
                    res = await self._run(skill, self._prompt(item, skill, extra), ws.path, ws.root, ws.author_env())
                    if not res.ok:
                        return {"status": "agent_failed", "error": res.error}
                    changed = await asyncio.to_thread(ws.commit_all, f"{ref}: {task.get('title')}\n\nsrs-task: {iid}/{ref}")
                    if not changed:
                        log.info("no_changes", key=key)
                        return {"status": "no_changes"}
                    if not repo.get("test_command"):
                        break
                    proc = await asyncio.to_thread(run_command, repo["test_command"], ws.path)
                    if proc.returncode == 0:
                        break
                    failure = _tail((proc.stdout or "") + "\n" + (proc.stderr or ""))
                    task = await self.srs.record(iid, ref)
                    n = await self._count(iid, ref, "ci_attempts", task, f"{key}:local:{ws.head()}", skill, f"local verification failed at {ws.head()[:7]}")
                    log.warning("verification_failed", key=key, attempt=n)
                    if n >= self.settings.max_ci_attempts:
                        draft_pr = True
                        break
                out = await self._publish(ws, iid, task, skill, key, draft_pr)
                if self.local:
                    out["evidence"] = await self._local_evidence(ws, repo, iid, ref, ran=bool(repo.get("test_command")))
                return {"status": "handoff" if draft_pr else "done", **out, "files": await asyncio.to_thread(ws.changed_files)}
            finally:
                ws.cleanup()

    async def _do_tests(self, item: dict) -> dict:
        skill = "write-tests"
        iid, ref, key = item["initiative_id"], item["ref"], item["key"]
        task = await self.srs.record(iid, ref)
        repo = await self._repo_or_gap(item, task, skill)
        if repo is None:
            return {"status": "blocked", "reason": "repo not ready"}
        branch = branch_name(self.settings.branch_prefix, iid, ref)
        async with self._branch_lock(repo["name"], branch):
            ws = await self._workspace(repo, iid, ref)
            try:
                res = await self._run(skill, self._prompt(item, skill, self._repo_brief(ws, repo, item)), ws.path, ws.root, ws.author_env())
                if not res.ok:
                    return {"status": "agent_failed", "error": res.error}
                changed = await asyncio.to_thread(ws.commit_all, f"{ref}: tests for {', '.join((task.get('fields') or {}).get('covers') or [])}\n\nsrs-task: {iid}/{ref}")
                if not changed:
                    return {"status": "no_changes"}
                sha = await asyncio.to_thread(ws.push)
                out = {"status": "done", "sha": sha, "files": await asyncio.to_thread(ws.changed_files)}
                task = await self.srs.record(iid, ref)
                state = (task.get("fields") or {}).get("pr_state")
                if self.local:
                    if state in ("draft", "open"):  # the branch head moved: the "PR" is at the new sha
                        await self._record(iid, ref, ws.pr_url, state, sha, skill, key, f"tests at {sha[:7]}")
                        out["pr"] = ws.pr_url
                        out["evidence"] = await self._local_evidence(ws, repo, iid, ref, ran=False)
                else:
                    pr = await self.github.find_pr(ws.repo, ws.branch)
                    if pr is not None and pr.state == "open":
                        await self._record(iid, ref, pr.html_url, pr.pr_state, sha, skill, key, f"PR #{pr.number} at {sha[:7]}")
                        out["pr"] = pr.html_url
                return out
            finally:
                ws.cleanup()

    async def _local_evidence(self, ws, repo: dict, iid: int, ref: str, ran: bool) -> Optional[str]:
        """Local mode has no CI: the runner (not the agent) runs the registry's test_command at
        the branch head and posts its JUnit report to the service, bound to that sha
        (`run_url: local:<repo>@<sha>`). That is the evidence GATE_PR reads; a RED run comes
        back as a `rework: ci` item. GitHub mode leaves this to the repo's CI."""
        cmd, junit = repo.get("test_command"), repo.get("junit_path")
        if not cmd or not junit:
            return None
        if not ran:
            await asyncio.to_thread(run_command, cmd, ws.path)
        report = ws.path / junit
        if not report.exists():
            log.warning("no_junit_report", repo=ws.repo, path=junit)
            return None
        sha = ws.head()
        try:
            out = await self.srs.junit(iid, ref, sha, self.settings.local_test_level, f"local:{ws.repo}@{sha}", report.read_text(), "runner-local-ci")
        except SrsError as e:
            log.warning("junit_rejected", key=f"{iid}:{ref}", error=str(e)[:300])
            return None
        finally:
            report.unlink(missing_ok=True)
        log.info("evidence_posted", ref=out.get("ref"), result=out.get("result"), sha=sha[:12])
        return out.get("ref")

    async def _do_pr_review(self, item: dict) -> dict:
        """review-pr through the Agent SDK against the branch diff (`git diff base...branch`) —
        local mode's review; in GitHub mode the Action does it on pull_request events."""
        skill = "review-pr"
        iid, ref, key = item["initiative_id"], item["ref"], item["key"]
        task = await self.srs.record(iid, ref)
        sha = (task.get("fields") or {}).get("pr_sha") or item.get("sha")
        repo = await self._repo_or_gap(item, task, skill)
        if repo is None:
            return {"status": "blocked", "reason": "repo not ready"}
        branch = branch_name(self.settings.branch_prefix, iid, ref)
        async with self._branch_lock(repo["name"], branch):
            ws = await self._workspace(repo, iid, ref)
            try:
                head = ws.head()
                if head != sha:
                    log.warning("review_sha_mismatch", key=key, recorded=sha, branch_head=head)
                extra = (
                    "## The change under review\n"
                    f"- Branch `{ws.branch}` of `{ws.repo}`, checked out at the working directory; HEAD SHA `{head}`.\n"
                    f"- The diff: `git diff {ws.default_branch}...{ws.branch}` (also `git log {ws.default_branch}..{ws.branch}`).\n"
                    f"- Bind every finding to at_sha `{head}`. There is no GitHub here: no inline comments, no `gh` —"
                    " findings are the review; put `path:line` in `where`.\n"
                )
                res = await self._run(skill, self._prompt(item, skill, extra), ws.path, ws.root, ws.author_env())
                if not res.ok:
                    return {"status": "agent_failed", "error": res.error}
                await self.srs.update(iid, ref, {"reviewed_sha": head}, f"{key}:reviewed:{head}", skill, f"review-pr pass at {head[:7]}")
                return {"status": "done", "sha": head}
            finally:
                ws.cleanup()

    def _repo_brief(self, ws, repo: dict, item: dict) -> str:
        if self.local:
            how = (
                "- This is a sandbox worktree: commit locally if you like. There is NO remote to push to and "
                "no GitHub — the branch and its head sha are the change the humans review; the runner records them.\n"
            )
        else:
            how = "- Commit locally if you like; do NOT push and do not open a PR — the runner pushes as the GitHub App and records pr_url / pr_sha.\n"
        return (
            "## Workspace\n"
            f"- Repository `{ws.repo}` at the working directory, on branch `{ws.branch}` "
            f"({'continuing the existing branch' if ws.branch_existed else f'new, from {ws.default_branch}'}).\n"
            f"- Verify with: `{repo.get('test_command') or '(no test command registered)'}`; JUnit report: `{repo.get('junit_path') or '—'}`.\n"
            f"- Paved-road templates for this repo: {', '.join(repo.get('templates') or []) or '—'}.\n" + how
        )
