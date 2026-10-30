"""Skills: `skills/<name>/SKILL.md` (frontmatter `name`, `description`; the body is the
procedure). The runner appends the body to Claude Code's system prompt and decides the
tool policy here — in code, not in the prompt file — so a skill can never widen its tools.

Which skill serves a work item (next_work kind):
  draft  → draft-from-ticket, then review-draft once the draft is submitted (same lease)
  review → draft-from-ticket (spec targets) · plan-to-tasks (task targets)
  plan   → plan-to-tasks
  task   → implement-task (repo workspace)
  tests  → write-tests (repo workspace, its own lease)
  pr_review → review-pr against the branch diff (local mode; in GitHub mode the Action runs it)
  (harvest-learnings: scheduled, `python -m runner harvest`)"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

SRS = "srs"  # the MCP server name the runner configures

# record-service MCP tools an agent may call (never claim/heartbeat/release: the runner owns
# the lease; never create_initiative / deploy_guard: not a skill's job)
READ_TOOLS = [
    "blueprint", "initiatives", "get_state", "next_work", "read_record", "search_records",
    "history", "gate_status", "drift_report", "inbox", "worklist", "activity", "repos",
    "kb_search", "kb_get",
]
WRITE_TOOLS = ["write", "resolve_review_item"]
FORBIDDEN_MCP = ["claim", "heartbeat", "release", "create_initiative", "deploy_guard"]


def mcp(*names: str) -> List[str]:
    return [f"mcp__{SRS}__{n}" for n in names]


# built-in tool sets
READ_ONLY = ["Read", "Glob", "Grep"]
CODE = ["Read", "Glob", "Grep", "Edit", "Write", "MultiEdit", "Bash", "TodoWrite"]
# denied even where Bash is allowed: pushing (the runner pushes with the App token), and
# reaching the network around the configured MCP servers
CODE_DENY = [
    "Bash(git push *)", "Bash(git remote *)", "Bash(git config *)", "Bash(curl *)", "Bash(wget *)",
    "Bash(gh *)", "WebFetch", "WebSearch",
] + mcp(*FORBIDDEN_MCP)
RECORDS_DENY = ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebSearch"] + mcp(*FORBIDDEN_MCP)


@dataclass
class Policy:
    allowed: List[str]
    disallowed: List[str]
    workspace: str  # repo | scratch
    max_turns: Optional[int] = None
    load_project_settings: bool = False  # setting_sources=["project"]: the repo's CLAUDE.md


POLICIES: Dict[str, Policy] = {
    "draft-from-ticket": Policy(READ_ONLY + ["WebFetch"] + mcp(*READ_TOOLS, *WRITE_TOOLS), RECORDS_DENY, "scratch", 60),
    "review-draft": Policy(READ_ONLY + mcp(*READ_TOOLS, "write"), RECORDS_DENY + ["WebFetch"], "scratch", 40),
    "plan-to-tasks": Policy(READ_ONLY + mcp(*READ_TOOLS, *WRITE_TOOLS), RECORDS_DENY + ["WebFetch"], "scratch", 50),
    "implement-task": Policy(CODE + mcp(*READ_TOOLS, "write"), CODE_DENY, "repo", None, True),
    "write-tests": Policy(CODE + mcp(*READ_TOOLS, "write"), CODE_DENY, "repo", None, True),
    # in the runner (local mode): read the branch diff with git, write findings; no edits, no gh
    "review-pr": Policy(
        READ_ONLY + ["Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git status *)"] + mcp(*READ_TOOLS, "write"),
        ["Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Bash(git push *)", "Bash(git commit *)", "Bash(gh *)", "Bash(curl *)"] + mcp(*FORBIDDEN_MCP),
        "repo",
        40,
        True,
    ),
    "harvest-learnings": Policy(READ_ONLY + mcp(*READ_TOOLS, "write"), RECORDS_DENY + ["WebFetch"], "scratch", 60),
}

KIND_SKILL = {"draft": "draft-from-ticket", "plan": "plan-to-tasks", "task": "implement-task", "tests": "write-tests", "pr_review": "review-pr"}


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    meta: dict = field(default_factory=dict)

    @property
    def policy(self) -> Policy:
        return POLICIES[self.name]


def parse(path: Path) -> Skill:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: SKILL.md needs a frontmatter block (name, description)")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    for key in ("name", "description"):
        if not meta.get(key):
            raise ValueError(f"{path}: frontmatter `{key}` is required")
    if meta["name"] != path.parent.name:
        raise ValueError(f"{path}: name {meta['name']!r} ≠ directory {path.parent.name!r}")
    return Skill(meta["name"], str(meta["description"]).strip(), body.strip(), path, meta)


def load_all(skills_dir: Path) -> Dict[str, Skill]:
    out = {}
    for p in sorted(skills_dir.glob("*/SKILL.md")):
        s = parse(p)
        out[s.name] = s
    missing = set(POLICIES) - set(out)
    if missing:
        raise ValueError(f"{skills_dir}: missing skills {sorted(missing)}")
    return out


def skill_for(item: dict) -> str:
    kind = item.get("kind")
    if kind == "review":
        target_type = (((item.get("context") or {}).get("record")) or {}).get("type")
        return "plan-to-tasks" if target_type == "task" else "draft-from-ticket"
    if kind not in KIND_SKILL:
        raise KeyError(f"no skill serves kind {kind!r}")
    return KIND_SKILL[kind]
