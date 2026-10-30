"""GitHub mode (WORKSPACE_MODE=github): a job's working copy, and the git/GitHub side of a task.

- The clone is shallow, over HTTPS, authenticated by a GitHub App installation token scoped
  to that one repository. The token is handed to git ONLY through the environment of each
  git command (GIT_CONFIG_COUNT/KEY/VALUE → `http.extraHeader`): it is never in argv, never in
  `.git/config`, never in the remote URL, and never in the environment of the agent.
- The branch is `harness/<initiative-id>-<task-ref>`. If it already exists on the remote
  (a rework round, or write-tests pushed first) the job continues it.
- Commits are made as the App's bot identity. The agent may commit too (its env carries the
  same author identity, nothing else); the runner commits whatever is left.
- Push retries through a fetch + rebase when another job (write-tests / implement-task)
  pushed to the branch meanwhile.
- `cleanup()` always runs (the worker calls it in `finally`).

`Scratch` is the same contract for skills that need no repository (a temp dir)."""

import base64
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from runner.log import log


class GitError(Exception):
    pass


def branch_name(prefix: str, initiative_id: int, task_ref: str) -> str:
    return f"{prefix}{initiative_id}-{task_ref}"


def auth_env(token: Optional[str]) -> Dict[str, str]:
    """git config passed through the environment (git ≥ 2.31), so nothing reaches disk."""
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/echo"}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"})
    return env


class Scratch:
    """A temp dir for skills that read and write records only."""

    def __init__(self, root: Path, label: str):
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=f"{label.replace(':', '_')}-", dir=root))

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


@dataclass
class Workspace:
    root: Path  # the job's dir: <root>/repo is the clone; job files live beside it
    repo: str  # owner/name
    clone_url: str
    default_branch: str
    branch: str
    author_name: str
    author_email: str
    token: Optional[str] = None
    base_sha: str = ""  # HEAD before the agent ran
    branch_existed: bool = False
    _env_extra: Dict[str, str] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.root / "repo"

    # ── git ──────────────────────────────────────────────────────────────

    def author_env(self) -> Dict[str, str]:
        return {
            "GIT_AUTHOR_NAME": self.author_name,
            "GIT_AUTHOR_EMAIL": self.author_email,
            "GIT_COMMITTER_NAME": self.author_name,
            "GIT_COMMITTER_EMAIL": self.author_email,
        }

    def git(self, *args: str, cwd: Optional[Path] = None, check: bool = True, auth: bool = False) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
        env.update(self.author_env())
        env.update(auth_env(self.token if auth else None))
        p = subprocess.run(["git", *args], cwd=str(cwd or self.path), env=env, capture_output=True, text=True, timeout=600)
        if check and p.returncode != 0:
            # never echo argv/env: the header lives in env only, but be safe with stderr too
            err = (p.stderr or "").replace(self.token or "\0", "***")
            raise GitError(f"git {args[0]} failed ({p.returncode}): {err.strip()[:500]}")
        return (p.stdout or "").strip()

    def prepare(self) -> "Workspace":
        """Shallow clone of the default branch; check out (or create) the harness branch."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.git("clone", "--depth", "50", "--no-tags", "--branch", self.default_branch, self.clone_url, str(self.path), cwd=self.root, auth=True)
        self.git("config", "user.name", self.author_name)
        self.git("config", "user.email", self.author_email)
        fetched = subprocess.run(
            ["git", "fetch", "--depth", "50", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}"],
            cwd=str(self.path),
            env={**os.environ, **auth_env(self.token)},
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.branch_existed = fetched.returncode == 0
        if self.branch_existed:
            self.git("checkout", "-B", self.branch, f"origin/{self.branch}")
        else:
            self.git("checkout", "-b", self.branch)
        self.base_sha = self.head()
        log.info("workspace_ready", repo=self.repo, branch=self.branch, continued=self.branch_existed, base=self.base_sha[:12])
        return self

    def exclude(self, path: str) -> None:
        """Never commit a generated file (the JUnit report)."""
        f = self.path / ".git" / "info" / "exclude"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a") as fh:
            fh.write(f"\n{path}\n")

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def dirty(self) -> bool:
        return bool(self.git("status", "--porcelain"))

    def commit_all(self, message: str) -> bool:
        """Commit whatever the agent left uncommitted. True when there is anything new on the
        branch since `prepare()` (agent commits included)."""
        if self.dirty():
            self.git("add", "-A")
            self.git("commit", "-q", "-m", message)
        return self.head() != self.base_sha

    def changed_files(self) -> List[str]:
        out = self.git("diff", "--name-only", f"{self.base_sha}..HEAD")
        return [x for x in out.splitlines() if x]

    def push(self, attempts: int = 3) -> str:
        """Push the branch; on a non-fast-forward, fetch + rebase onto the remote branch and
        retry. Returns the pushed head sha."""
        last = ""
        for i in range(attempts):
            try:
                self.git("push", "origin", f"HEAD:refs/heads/{self.branch}", auth=True)
                sha = self.head()
                log.info("pushed", repo=self.repo, branch=self.branch, sha=sha[:12], attempt=i + 1)
                return sha
            except GitError as e:
                last = str(e)
                self.git("fetch", "--depth", "50", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}", auth=True, check=False)
                try:
                    self.git("rebase", f"origin/{self.branch}")
                except GitError:
                    self.git("rebase", "--abort", check=False)
                    raise
        raise GitError(f"push failed after {attempts} attempts: {last}")

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.token = None


def run_command(cmd: str, cwd: Path, timeout: int = 1800, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """The registry's test_command (a human set it), in the clone, without the runner's
    secrets in its environment."""
    clean = {k: v for k, v in os.environ.items() if k not in ("SRS_TOKEN", "ANTHROPIC_API_KEY") and not k.startswith("GITHUB_")}
    clean.update(env or {})
    return subprocess.run(cmd, shell=True, cwd=str(cwd), env=clean, capture_output=True, text=True, timeout=timeout)
