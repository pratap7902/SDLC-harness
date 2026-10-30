"""Building a Worker wired to the test service, the fake GitHub and the fake agent; the
scripted skills."""

import asyncio
import json
from pathlib import Path
from typing import Dict

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from runner.config import Settings
from runner.github_app import GithubApp
from runner.skills import load_all
from runner.srs_client import SrsClient
from runner.tests.fakes import Ctx, FakeAgent, FakeGithub
from runner.worker import Worker
from tests.fixtures.slice import draft_batch

ROOT = Path(__file__).resolve().parents[2]
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
PUBLIC_PEM = _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def make_worker(srs, tmp_path, scripts: Dict, kinds, gh: FakeGithub = None, concurrency: int = 1, mode: str = "local", **overrides):
    """mode="local" (the default, like the runner's): no GitHub object at all."""
    settings = Settings(
        workspace_mode=mode,
        srs_url=srs.url,
        srs_token=srs.tokens["runner"],
        kinds=list(kinds),
        concurrency=concurrency,
        work_root=tmp_path / "work",
        skills_dir=ROOT / "skills",
        github_app_id="12345",
        github_private_key=PRIVATE_PEM,
        github_installation_id="777",
        github_app_slug="sdlc-harness-test",
        heartbeat_s=overrides.pop("heartbeat_s", 30),  # SQLite in tests: keep concurrent writes rare
        **overrides,
    )
    app = None
    if mode == "github":
        gh = gh or FakeGithub()
        app = GithubApp(settings.github_app_id, PRIVATE_PEM, "https://api.github.test", "777", "sdlc-harness-test", transport=gh.transport())
    agent = FakeAgent(scripts)
    worker = Worker(settings, srs=SrsClient(srs.url, srs.tokens["runner"]), github=app, query_fn=agent, skills=load_all(settings.skills_dir))
    return worker, agent, gh


def run(worker) -> list:
    async def go():
        try:
            return await worker.run_until_idle()
        finally:
            await worker.srs.aclose()
            if worker.github is not None:
                await worker.github.aclose()

    return asyncio.run(go())


# ── scripted skills ──────────────────────────────────────────────────────────


async def draft_skill(ctx: Ctx):
    iid = ctx.item["initiative_id"]
    await ctx.tool("get_state", initiative_id=iid)
    await ctx.tool("write", initiative_id=iid, ops=draft_batch(), batch_id=f"{ctx.item['key']}:draft", agent="draft-from-ticket")


async def revise_skill(ctx: Ctx):
    """The `review` item after G-1 was answered: D-2 still holds, with the reason."""
    iid = ctx.item["initiative_id"]
    target = ctx.item["title"].split(" ")[0]
    await ctx.tool("write", initiative_id=iid, ops=[{"ref": target, "fields": {"rationale": "G-1: billing needs per-order ordering."}, "note": "per G-1"}], batch_id=f"{ctx.item['key']}:revise", agent="draft-from-ticket")


async def review_draft_skill(ctx: Ctx):
    iid = ctx.item["initiative_id"]
    draft = await ctx.tool("read_record", initiative_id=iid, refs=["draft"], as_json=True)
    rev = json.loads(draft)["rev"]
    finding = {"type": "finding", "title": "LLD names no relay batch size", "fields": {"summary": "LLD does not say how many outbox rows the relay takes per poll", "severity": "minor", "target": ["draft"], "at_rev": str(rev), "where": "draft.lld"}}
    await ctx.tool("write", initiative_id=iid, ops=[finding], batch_id=f"{ctx.item['key']}:review", agent="review-draft")


def plan_skill_for(repo: str):
    async def script(ctx: Ctx):
        await _plan(ctx, repo)

    return script


async def plan_skill(ctx: Ctx):
    await _plan(ctx, "example/orders")


async def _plan(ctx: Ctx, repo: str):
    iid = ctx.item["initiative_id"]
    ctx.notes["repos"] = await ctx.tool("repos")
    task = {"type": "task", "title": "Outbox table and relay", "fields": {"goal": "Write order events through the outbox", "repo": repo, "template": "python-service", "implements": ["D-1", "D-2"], "covers": ["AC-1", "AC-2", "AC-3"], "rollback": "Disable order_events.enabled"}}
    await ctx.tool("write", initiative_id=iid, ops=[task], batch_id=f"{ctx.item['key']}:plan", agent="plan-to-tasks")


def implement_skill(counter=None):
    async def script(ctx: Ctx):
        await ctx.tool("read_record", initiative_id=ctx.item["initiative_id"], refs=[ctx.item["ref"]])
        (ctx.cwd / "orders").mkdir(exist_ok=True)
        n = (counter or {}).get("n", 0) + 1
        if counter is not None:
            counter["n"] = n
        (ctx.cwd / "orders" / "relay.py").write_text(f"# relay, round {n}\nBATCH = 100\n")

    return script


async def write_tests_skill(ctx: Ctx):
    (ctx.cwd / "tests").mkdir(exist_ok=True)
    (ctx.cwd / "tests" / "test_relay.py").write_text("def test_AC_1_outbox_row():\n    pass\n\n\ndef test_AC_2_relay():\n    pass\n\n\ndef test_AC_3_key():\n    pass\n")


async def review_pr_skill(ctx: Ctx):
    """Reads the branch diff the way the skill says, files one nit at the head sha."""
    import re
    import subprocess

    m = re.search(r"HEAD SHA `([0-9a-f]+)`", ctx.prompt)
    head = m.group(1)
    diff_cmd = re.search(r"`(git diff [^`]+)`", ctx.prompt).group(1)
    ctx.notes["diff"] = subprocess.run(diff_cmd.split(), cwd=ctx.cwd, capture_output=True, text=True).stdout
    finding = {"type": "finding", "title": "Name the batch size constant", "fields": {"summary": "BATCH should say what it limits", "severity": "nit", "target": [ctx.item["ref"]], "at_sha": head, "where": "orders/relay.py:2"}}
    await ctx.tool("write", initiative_id=ctx.item["initiative_id"], ops=[finding], batch_id=f"{ctx.item['key']}:{head[:7]}", agent="review-pr")
