"""Local mode (the default): no GitHub, no network, no push.

A registry entry names a repository on the runner host (`local_path`). The runner keeps one
**sandbox** per repository — a bare `git clone --local` of that path under
`RUNNER_WORK_ROOT/sandboxes/` — and never touches the original. Its push URL is set to
`no_push`, so a push from the sandbox or any of its worktrees fails.

Each job gets a `git worktree` of the sandbox on branch `harness/<initiative-id>-<task-ref>`
(created from the base branch the first time, continued afterwards). Commits made in the
worktree land straight in the sandbox's refs — that branch and its head sha ARE the "PR":
the task records `pr_url = local:<repo>@<branch>` and `pr_sha = <head>`; a human reviews it
with `git -C <sandbox> diff <base>...<branch>` and approves that sha in the harness UI.

Two jobs on the same branch (implement-task, write-tests) are serialised by the worker:
git does not let two worktrees check out one branch."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from runner.log import log
from runner.workspace import GitError

NO_PUSH = "no_push"


def _git(*args: str, cwd: Path, env: Optional[Dict[str, str]] = None, check: bool = True) -> str:
    full = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    full.update(env or {})
    full["GIT_TERMINAL_PROMPT"] = "0"
    p = subprocess.run(["git", *args], cwd=str(cwd), env=full, capture_output=True, text=True, timeout=600)
    if check and p.returncode != 0:
        raise GitError(f"git {args[0]} failed ({p.returncode}): {(p.stderr or '').strip()[:500]}")
    return (p.stdout or "").strip()


def sandbox_path(work_root: Path, name: str) -> Path:
    return work_root / "sandboxes" / (re.sub(r"[^A-Za-z0-9._-]+", "_", name) + ".git")


def ensure_sandbox(work_root: Path, name: str, local_path: str, base: str) -> Path:
    """Create the repository's sandbox once (bare, `--local`), then refresh its base branch
    from the original on every job. Harness branches live only in the sandbox."""
    src = Path(local_path).expanduser()
    if not (src / ".git").exists() and not (src / "HEAD").exists():
        raise GitError(f"local_path {local_path} is not a git repository")
    sb = sandbox_path(work_root, name)
    if not sb.exists():
        sb.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--local", "--bare", "--quiet", str(src), str(sb), cwd=sb.parent)
        log.info("sandbox_created", repo=name, sandbox=str(sb))
    _git("remote", "set-url", "--push", "origin", NO_PUSH, cwd=sb)
    _git("fetch", "--quiet", "origin", f"+refs/heads/{base}:refs/heads/{base}", cwd=sb)
    _git("worktree", "prune", cwd=sb, check=False)
    return sb


@dataclass
class LocalWorkspace:
    root: Path  # the job's dir; <root>/repo is the worktree
    repo: str
    sandbox: Path
    default_branch: str
    branch: str
    author_name: str = "sdlc-harness[bot]"
    author_email: str = "sdlc-harness[bot]@users.noreply.local"
    base_sha: str = ""
    branch_existed: bool = False
    _env: Dict[str, str] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.root / "repo"

    @property
    def pr_url(self) -> str:
        return f"local:{self.repo}@{self.branch}"

    def author_env(self) -> Dict[str, str]:
        return {
            "GIT_AUTHOR_NAME": self.author_name,
            "GIT_AUTHOR_EMAIL": self.author_email,
            "GIT_COMMITTER_NAME": self.author_name,
            "GIT_COMMITTER_EMAIL": self.author_email,
        }

    def git(self, *args: str, check: bool = True) -> str:
        return _git(*args, cwd=self.path, env=self.author_env(), check=check)

    def exclude(self, path: str) -> None:
        """Never commit a generated file (the JUnit report): info/exclude is shared by every
        worktree of the sandbox."""
        if not path:
            return
        f = self.sandbox / "info" / "exclude"
        f.parent.mkdir(parents=True, exist_ok=True)
        lines = f.read_text().splitlines() if f.exists() else []
        if path not in lines:
            f.write_text("\n".join(lines + [path]) + "\n")

    def prepare(self) -> "LocalWorkspace":
        self.root.mkdir(parents=True, exist_ok=True)
        self.branch_existed = bool(_git("rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}", cwd=self.sandbox, check=False))
        if self.branch_existed:
            _git("worktree", "add", "--quiet", str(self.path), self.branch, cwd=self.sandbox)
        else:
            _git("worktree", "add", "--quiet", "-b", self.branch, str(self.path), self.default_branch, cwd=self.sandbox)
        self.base_sha = self.head()
        log.info("workspace_ready", mode="local", repo=self.repo, branch=self.branch, continued=self.branch_existed, base=self.base_sha[:12])
        return self

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def dirty(self) -> bool:
        return bool(self.git("status", "--porcelain"))

    def commit_all(self, message: str) -> bool:
        if self.dirty():
            self.git("add", "-A")
            self.git("commit", "-q", "-m", message)
        return self.head() != self.base_sha

    def changed_files(self) -> List[str]:
        return [x for x in self.git("diff", "--name-only", f"{self.base_sha}..HEAD").splitlines() if x]

    def diff_stat(self) -> str:
        return self.git("diff", "--stat", f"{self.default_branch}...{self.branch}")

    def push(self, attempts: int = 1) -> str:
        """Local mode never pushes: the branch already is in the sandbox."""
        return self.head()

    def cleanup(self) -> None:
        _git("worktree", "remove", "--force", str(self.path), cwd=self.sandbox, check=False)
        shutil.rmtree(self.root, ignore_errors=True)
        _git("worktree", "prune", cwd=self.sandbox, check=False)
