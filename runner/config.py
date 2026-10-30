"""Runner settings, from the environment (or a .env the deployment mounts). Secrets that the
agent's tools must not see (the GitHub App private key) are read here and then REMOVED from
os.environ: the Agent SDK passes the runner's environment on to Claude Code, whose Bash tool
would otherwise be able to print them. (Docker mode isolates further: see docs/runner.md.)"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Work-item kinds (next_work) → the skill that serves them.
DEFAULT_KINDS = ("draft", "review", "plan", "task", "tests")
# API-key auth, or a documented cloud provider (Agent SDK docs). claude.ai login is not used.
PROVIDER_ENV = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_ANTHROPIC_AWS")
SCRUBBED = ("GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_WEBHOOK_SECRET")


def _int(env: Dict[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    return int(raw) if raw else default


def _float(env: Dict[str, str], key: str, default: Optional[float]) -> Optional[float]:
    raw = (env.get(key) or "").strip()
    return float(raw) if raw else default


@dataclass
class Settings:
    # the record service
    srs_url: str = "http://localhost:8791"
    srs_token: str = ""  # an agent token (scripts/mint_token.py … --kind agent)
    principal: str = "runner-sdk"  # informational: the token decides who we are
    # the loop
    kinds: List[str] = field(default_factory=lambda: list(DEFAULT_KINDS))
    concurrency: int = 2
    poll_interval_s: float = 20.0
    lease_ttl_min: int = 15
    heartbeat_s: float = 120.0
    # the model
    model: str = "claude-opus-5-5"
    # Claude Code CLI the SDK drives: empty → the one bundled with claude-agent-sdk. Auth is
    # API-key based (ANTHROPIC_API_KEY) or the documented Bedrock / Vertex / Foundry /
    # Claude Platform on AWS env vars — never a claude.ai login or subscription.
    cli_path: str = ""
    max_turns: int = 80
    max_budget_usd: Optional[float] = 15.0
    skills_dir: Path = Path(__file__).resolve().parent.parent / "skills"
    # where work happens
    work_root: Path = Path(os.environ.get("TMPDIR", "/tmp")) / "harness-runner"
    execution_mode: str = "local"  # local | docker
    docker_image: str = "sdlc-harness-runner:latest"
    docker_network: str = ""
    # GitHub App
    github_api_url: str = "https://api.github.com"
    github_app_id: str = ""
    github_app_slug: str = ""
    github_private_key: str = ""  # PEM; from GITHUB_APP_PRIVATE_KEY or …_PATH (scrubbed from env)
    github_installation_id: str = ""  # empty → looked up per repo
    github_bot_user_id: str = ""  # empty → looked up from <slug>[bot]
    branch_prefix: str = "harness/"
    # handoff (blueprint/lifecycle.yaml handoff:)
    max_ci_attempts: int = 3
    max_review_rounds: int = 3
    # extra MCP servers for the agent, as JSON {"name": {"type": "http", "url": …}} (optional)
    extra_mcp_json: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None, scrub: bool = True) -> "Settings":
        from_os = env is None
        env = dict(os.environ if env is None else env)
        key = env.get("GITHUB_APP_PRIVATE_KEY", "")
        key_path = env.get("GITHUB_APP_PRIVATE_KEY_PATH", "")
        if not key and key_path:
            key = Path(key_path).read_text()
        s = cls(
            srs_url=(env.get("SRS_URL") or cls.srs_url).rstrip("/"),
            srs_token=env.get("SRS_TOKEN", ""),
            principal=env.get("RUNNER_PRINCIPAL", cls.principal),
            kinds=[k.strip() for k in (env.get("RUNNER_KINDS") or ",".join(DEFAULT_KINDS)).split(",") if k.strip()],
            concurrency=_int(env, "RUNNER_CONCURRENCY", cls.concurrency),
            poll_interval_s=float(env.get("RUNNER_POLL_INTERVAL_S") or cls.poll_interval_s),
            lease_ttl_min=_int(env, "RUNNER_LEASE_TTL_MIN", cls.lease_ttl_min),
            heartbeat_s=float(env.get("RUNNER_HEARTBEAT_S") or cls.heartbeat_s),
            model=env.get("RUNNER_MODEL") or cls.model,
            cli_path=env.get("CLAUDE_CLI_PATH", ""),
            max_turns=_int(env, "RUNNER_MAX_TURNS", cls.max_turns),
            max_budget_usd=_float(env, "RUNNER_MAX_BUDGET_USD", cls.max_budget_usd),
            skills_dir=Path(env["RUNNER_SKILLS_DIR"]) if env.get("RUNNER_SKILLS_DIR") else cls.skills_dir,
            work_root=Path(env["RUNNER_WORK_ROOT"]) if env.get("RUNNER_WORK_ROOT") else cls.work_root,
            execution_mode=(env.get("RUNNER_EXECUTION_MODE") or cls.execution_mode).lower(),
            docker_image=env.get("RUNNER_DOCKER_IMAGE") or cls.docker_image,
            docker_network=env.get("RUNNER_DOCKER_NETWORK", ""),
            github_api_url=(env.get("GITHUB_API_URL") or cls.github_api_url).rstrip("/"),
            github_app_id=env.get("GITHUB_APP_ID", ""),
            github_app_slug=env.get("GITHUB_APP_SLUG", ""),
            github_private_key=key,
            github_installation_id=env.get("GITHUB_INSTALLATION_ID", ""),
            github_bot_user_id=env.get("GITHUB_BOT_USER_ID", ""),
            branch_prefix=env.get("HARNESS_BRANCH_PREFIX") or cls.branch_prefix,
            max_ci_attempts=_int(env, "RUNNER_MAX_CI_ATTEMPTS", cls.max_ci_attempts),
            max_review_rounds=_int(env, "RUNNER_MAX_REVIEW_ROUNDS", cls.max_review_rounds),
            extra_mcp_json=env.get("RUNNER_EXTRA_MCP_JSON", ""),
            log_level=env.get("RUNNER_LOG_LEVEL", "INFO"),
        )
        if scrub and from_os:
            for name in SCRUBBED:
                os.environ.pop(name, None)
        if s.execution_mode not in ("local", "docker"):
            raise ValueError("RUNNER_EXECUTION_MODE: local | docker")
        return s

    @staticmethod
    def api_auth() -> str:
        """How the Agent SDK will authenticate: `ANTHROPIC_API_KEY` or a documented cloud
        provider. Empty → the runner refuses to start: it never falls back to a claude.ai
        login or subscription (not allowed for products built on the Agent SDK)."""
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY"
        return next((v for v in PROVIDER_ENV if os.environ.get(v)), "")

    def problems(self) -> List[str]:
        """What stops this runner from working (printed by `python -m runner check`)."""
        out = []
        if not self.srs_token:
            out.append("SRS_TOKEN: an agent token for the record service (make token ACTOR=runner-sdk KIND=agent)")
        if not self.api_auth():
            out.append("ANTHROPIC_API_KEY (or a documented cloud provider: " + " / ".join(PROVIDER_ENV) + "): how the Agent SDK authenticates — never a claude.ai login")
        if self.cli_path and not Path(self.cli_path).exists():
            out.append(f"CLAUDE_CLI_PATH: {self.cli_path} does not exist (unset it to use the CLI bundled with claude-agent-sdk)")
        if {"task", "tests"} & set(self.kinds):
            if not self.github_app_id or not self.github_private_key:
                out.append("GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY(_PATH): the GitHub App the runner pushes and opens PRs as")
        if not self.skills_dir.is_dir():
            out.append(f"RUNNER_SKILLS_DIR: {self.skills_dir} is not a directory")
        return out
