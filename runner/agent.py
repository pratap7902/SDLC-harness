"""Running one skill with the Claude Agent SDK (`claude_agent_sdk.query`).

Options (see https://code.claude.com/docs/en/agent-sdk/python):
- `cwd`: the clone (repo skills) or a scratch dir;
- `system_prompt`: Claude Code's preset with the skill's SKILL.md appended;
- `setting_sources=["project"]` for repo skills, so the target repo's CLAUDE.md and
  .claude/settings.json load; `[]` otherwise;
- `mcp_servers`: the record service's MCP (`srs`, bearer agent token) — which also serves the
  knowledge-base tools kb_search / kb_get — plus RUNNER_EXTRA_MCP_JSON; `strict_mcp_config`
  so a repo's own .mcp.json cannot add servers;
- `allowed_tools` / `disallowed_tools` from runner/skills.py, `permission_mode="dontAsk"`
  (anything not pre-approved is denied — there is nobody to ask);
- `model`, `max_turns`, `max_budget_usd` from settings.

`QueryFn` is the seam tests replace with a scripted fake."""

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from runner.config import Settings
from runner.log import log
from runner.skills import SRS, Skill

QueryFn = Callable[..., AsyncIterator[Any]]

PREAMBLE = """\
You are running unattended inside the SDLC harness runner, as the skill below. There is no
human in this session: never wait for an answer — anything only a human can decide becomes a
gap record (or a finding) in the record service, and you stop that line of work.
The runner holds the lease on your work item; do not call claim, heartbeat or release.
"""


@dataclass
class AgentResult:
    ok: bool
    subtype: str = ""
    num_turns: int = 0
    cost_usd: Optional[float] = None
    duration_s: float = 0.0
    result: str = ""
    error: str = ""
    tool_calls: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def mcp_servers(settings: Settings) -> Dict[str, dict]:
    servers: Dict[str, dict] = {
        SRS: {"type": "http", "url": f"{settings.srs_url}/mcp", "headers": {"Authorization": f"Bearer {settings.srs_token}"}}
    }
    if settings.extra_mcp_json:
        servers.update(json.loads(settings.extra_mcp_json))
    return servers


def build_options(settings: Settings, skill: Skill, cwd: Path, env: Optional[Dict[str, str]] = None):
    from claude_agent_sdk import ClaudeAgentOptions

    policy = skill.policy
    return ClaudeAgentOptions(
        cwd=str(cwd),
        model=settings.model,
        cli_path=settings.cli_path or None,  # None → the CLI bundled with claude-agent-sdk
        system_prompt={"type": "preset", "preset": "claude_code", "append": PREAMBLE + "\n" + skill.body},
        setting_sources=["project"] if policy.load_project_settings else [],
        mcp_servers=mcp_servers(settings),
        strict_mcp_config=True,
        allowed_tools=list(policy.allowed),
        disallowed_tools=list(policy.disallowed),
        permission_mode="dontAsk",
        max_turns=policy.max_turns or settings.max_turns,
        max_budget_usd=settings.max_budget_usd,
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": "sdlc-harness-runner/0.1", **(env or {})},
    )


async def run_skill(settings: Settings, skill: Skill, prompt: str, cwd: Path, env: Optional[Dict[str, str]] = None, query_fn: Optional[QueryFn] = None) -> AgentResult:
    """Run the skill to completion. Never raises for an agent failure: the result says."""
    from claude_agent_sdk import AssistantMessage, ClaudeSDKError, ResultMessage, ToolUseBlock

    if query_fn is None:
        from claude_agent_sdk import query as query_fn  # noqa: N813

    options = build_options(settings, skill, cwd, env)
    started = time.monotonic()
    out = AgentResult(ok=False)
    try:
        async for message in query_fn(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        out.tool_calls.append(block.name)
            elif isinstance(message, ResultMessage):
                out.subtype = message.subtype
                out.num_turns = message.num_turns
                out.cost_usd = message.total_cost_usd
                out.result = (message.result or "")[:4000]
                out.ok = not message.is_error
                if message.is_error:
                    out.error = "; ".join(message.errors or []) or (message.stop_reason or message.subtype)
    except ClaudeSDKError as e:  # ResultError, ProcessError, CLINotFoundError, …
        out.ok = False
        out.subtype = getattr(e, "subtype", None) or type(e).__name__
        out.error = str(e)[:2000]
    except Exception as e:  # noqa: BLE001 — a skill run must never take the worker down
        out.ok = False
        out.subtype = type(e).__name__
        out.error = str(e)[:2000]
    out.duration_s = round(time.monotonic() - started, 1)
    log.info(
        "skill_finished",
        skill=skill.name,
        ok=out.ok,
        subtype=out.subtype,
        turns=out.num_turns,
        cost_usd=out.cost_usd,
        duration_s=out.duration_s,
        tools=len(out.tool_calls),
        error=out.error[:300] or None,
    )
    return out


def cli_info(settings: Settings) -> Dict[str, str]:
    """The Claude Code CLI the SDK will drive and its version (logged at startup)."""
    import shutil

    path = settings.cli_path
    source = "CLAUDE_CLI_PATH"
    if not path:
        source = "bundled"
        try:
            import claude_agent_sdk

            pkg = Path(claude_agent_sdk.__file__).parent
            found = [p for p in pkg.rglob("claude") if p.is_file()]
            path = str(found[0]) if found else ""
        except Exception:  # noqa: BLE001
            path = ""
        if not path:
            path, source = shutil.which("claude") or "", "PATH"
    version = ""
    if path:
        try:
            version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        except Exception as e:  # noqa: BLE001
            version = f"unknown ({type(e).__name__})"
    return {"cli_path": path or "(not found)", "cli_source": source, "cli_version": version}


# ── docker mode ──────────────────────────────────────────────────────────────


def docker_command(settings: Settings, job_dir: Path, network: str = "") -> List[str]:
    """`docker run` for one job: the job dir (clone + job.json) is the only mount; the
    container gets the Anthropic key and the record-service token — never the GitHub App
    key or an installation token (the host runner pushes)."""
    import os

    # same uid as the runner so the clone stays writable on both sides; HOME for Claude Code's state
    cmd = ["docker", "run", "--rm", "--init", "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp", "-v", f"{job_dir}:/job", "-w", "/job/repo"]
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS", "ANTHROPIC_AWS_WORKSPACE_ID", "SRS_TOKEN", "SRS_URL", "RUNNER_MODEL", "RUNNER_MAX_TURNS", "RUNNER_MAX_BUDGET_USD", "RUNNER_EXTRA_MCP_JSON"):
        cmd += ["-e", name]
    if network or settings.docker_network:
        cmd += ["--network", network or settings.docker_network]
    cmd += [settings.docker_image, "exec-job", "/job/job.json"]  # the image's entrypoint is `python -m runner`
    return cmd


async def run_in_docker(settings: Settings, skill: Skill, prompt: str, job_dir: Path, env: Optional[Dict[str, str]] = None) -> AgentResult:
    import asyncio
    import os

    (job_dir / "job.json").write_text(json.dumps({"skill": skill.name, "prompt": prompt, "cwd": "/job/repo" if (job_dir / "repo").exists() else "/job", "env": env or {}}))
    cmd = docker_command(settings, job_dir)
    child_env = {**os.environ, "SRS_TOKEN": settings.srs_token, "SRS_URL": settings.srs_url}
    proc = await asyncio.to_thread(subprocess.run, cmd, env=child_env, capture_output=True, text=True)
    result_path = job_dir / "result.json"
    if result_path.exists():
        return AgentResult(**json.loads(result_path.read_text()))
    return AgentResult(ok=False, subtype="docker", error=(proc.stderr or proc.stdout or "")[-2000:])
