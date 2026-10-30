"""Test doubles: a scripted Agent SDK `query` and a GitHub REST API on httpx.MockTransport."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

SKILL_RE = re.compile(r"Run the `([a-z-]+)` skill")
ITEM_RE = re.compile(r"## Work item\n```json\n(.*?)\n```", re.S)


# ── the agent ────────────────────────────────────────────────────────────────


class McpClient:
    """Calls the record service's MCP tools exactly as Claude Code would: JSON-RPC over the
    streamable-HTTP endpoint and headers the runner put in options.mcp_servers."""

    def __init__(self, server: dict):
        self.url = server["url"]
        self.headers = {**server.get("headers", {}), "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    async def call(self, tool: str, **arguments) -> str:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.url, json=body, headers=self.headers)
        r.raise_for_status()
        out = r.json()
        if "error" in out:
            raise RuntimeError(out["error"].get("message"))
        text = "\n".join(c.get("text", "") for c in out["result"].get("content", []))
        if out["result"].get("isError"):
            raise RuntimeError(f"{tool}: {text}")
        return text


@dataclass
class Ctx:
    skill: str
    prompt: str
    item: dict
    cwd: Path
    options: object
    mcp: McpClient
    calls: List[str] = field(default_factory=list)
    notes: Dict[str, object] = field(default_factory=dict)

    async def tool(self, name: str, **args) -> str:
        self.calls.append(name)
        return await self.mcp.call(name, **args)


Script = Callable[[Ctx], "object"]


class FakeAgent:
    """`query(prompt=…, options=…)` replacement. `scripts[skill]` is an async function
    (ctx) → None that does the skill's tool calls and file edits; raise to simulate a crash,
    return "error" to end with an error result."""

    def __init__(self, scripts: Dict[str, Script]):
        self.scripts = scripts
        self.runs: List[Ctx] = []

    async def __call__(self, *, prompt: str, options, transport=None):
        skill = SKILL_RE.search(prompt).group(1)
        item = json.loads(ITEM_RE.search(prompt).group(1))
        ctx = Ctx(skill, prompt, item, Path(options.cwd), options, McpClient(options.mcp_servers["srs"]))
        ctx.notes["claude_md"] = (ctx.cwd / "CLAUDE.md").exists()  # the workspace is gone after the job
        self.runs.append(ctx)
        outcome = await self.scripts[skill](ctx)
        for name in ctx.calls:
            yield AssistantMessage(content=[ToolUseBlock(id=f"t{len(name)}", name=f"mcp__srs__{name}", input={})], model="claude-opus-5-5")
        yield AssistantMessage(content=[TextBlock(text=f"{skill} done")], model="claude-opus-5-5")
        err = outcome == "error"
        yield ResultMessage(
            subtype="error_max_turns" if err else "success",
            duration_ms=5,
            duration_api_ms=3,
            is_error=err,
            num_turns=len(ctx.calls) + 1,
            session_id="fake",
            total_cost_usd=0.01,
            result=None if err else f"{skill} done",
            errors=["max turns"] if err else None,
        )

    def runs_of(self, skill: str) -> List[Ctx]:
        return [r for r in self.runs if r.skill == skill]


# ── GitHub ───────────────────────────────────────────────────────────────────


class FakeGithub:
    """Enough of the GitHub REST API for the runner: installation tokens and pulls."""

    def __init__(self, owner_repo: str = "example/orders"):
        self.owner_repo = owner_repo
        self.requests: List[httpx.Request] = []
        self.prs: Dict[int, dict] = {}
        self.tokens_issued = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _pr_json(self, n: int) -> dict:
        return self.prs[n]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        auth = request.headers.get("authorization", "")
        if method == "POST" and re.fullmatch(r"/app/installations/\d+/access_tokens", path):
            assert auth.startswith("Bearer ey"), "access_tokens needs the App JWT"
            self.tokens_issued += 1
            return httpx.Response(201, json={"token": f"ghs_fake{self.tokens_issued}", "expires_at": "2099-01-01T00:00:00Z", "repositories": json.loads(request.content)["repositories"]})
        assert auth.startswith("Bearer ghs_fake"), f"{method} {path} needs an installation token"
        if method == "GET" and path.startswith("/users/"):
            return httpx.Response(200, json={"id": 4242, "login": path.split("/")[-1]})
        base = f"/repos/{self.owner_repo}/pulls"
        if path == base and method == "GET":
            head = request.url.params.get("head", "").split(":", 1)[-1]
            return httpx.Response(200, json=[p for p in self.prs.values() if p["head"]["ref"] == head])
        if path == base and method == "POST":
            body = json.loads(request.content)
            n = len(self.prs) + 1
            self.prs[n] = {
                "number": n,
                "html_url": f"https://github.com/{self.owner_repo}/pull/{n}",
                "state": "open",
                "draft": body.get("draft", False),
                "merged": False,
                "title": body["title"],
                "body": body["body"],
                "head": {"ref": body["head"], "sha": ""},
                "base": {"ref": body["base"]},
            }
            return httpx.Response(201, json=self.prs[n])
        m = re.fullmatch(rf"{base}/(\d+)", path)
        if m and int(m.group(1)) in self.prs:
            n = int(m.group(1))
            if method == "PATCH":
                self.prs[n].update(json.loads(request.content))
            return httpx.Response(200, json=self.prs[n])
        return httpx.Response(404, json={"message": "Not Found"})


def bare_head(bare: Path, branch: str) -> Optional[str]:
    import subprocess

    p = subprocess.run(["git", "rev-parse", f"refs/heads/{branch}"], cwd=str(bare), capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def bare_file(bare: Path, branch: str, path: str) -> Optional[str]:
    import subprocess

    p = subprocess.run(["git", "show", f"{branch}:{path}"], cwd=str(bare), capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None
