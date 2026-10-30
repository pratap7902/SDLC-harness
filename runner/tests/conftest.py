"""Runner tests: no network, no model.

- The record service runs for real, as a subprocess of the SERVICE's own venv (its `mcp` pin
  differs from the Agent SDK's, which is why the runner deploys separately), on a throwaway
  SQLite file, AUTH_MODE=token, with tokens minted by scripts/mint_token.py.
- GitHub is a local bare repository (git over file://) plus an httpx.MockTransport that
  plays the REST API (installation tokens, pulls).
- The Agent SDK's `query` is replaced by `FakeAgent` (runner/tests/fakes.py), which performs
  scripted MCP tool calls against the real service and scripted edits in the workspace."""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE_PY = Path(os.environ.get("SRS_PYTHON") or ROOT / ".venv" / "bin" / "python")
TOKENS = {"runner": ("runner-sdk", "agent"), "ci": ("ci-bot", "agent"), "chandra": ("chandra", "human"), "priya": ("priya", "human"), "maya": ("maya", "human")}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def service(tmp_path_factory):
    if not SERVICE_PY.exists():
        pytest.skip(f"the record service's venv is missing ({SERVICE_PY}): run `make install` (or set SRS_PYTHON)")
    tmp = tmp_path_factory.mktemp("srs")
    db = tmp / "srs.db"
    env = {
        **{k: v for k, v in os.environ.items() if k not in ("AUTH_MODE", "DATABASE_URL")},
        "DATABASE_URL": f"sqlite+pysqlite:///{db}",
        "APP_ENV": "testing",
        "AUTH_MODE": "token",
        "BLUEPRINT_DIR": str(ROOT / "blueprint"),
        "REVIEW_PROPAGATION": "true",
    }
    bindir = SERVICE_PY.parent
    subprocess.run([str(bindir / "alembic"), "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True)
    tokens = {}
    for name, (principal, kind) in TOKENS.items():
        out = subprocess.run(
            [str(SERVICE_PY), "scripts/mint_token.py", "mint", "--actor", principal, "--kind", kind, "--roles", "", "--label", "runner tests", "--days", "0"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        ).stdout
        tokens[name] = next(w for w in out.split() if w.startswith("srs_"))
    port = _free_port()
    log = open(tmp / "service.log", "w")
    proc = subprocess.Popen([str(bindir / "uvicorn"), "main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError((tmp / "service.log").read_text())
    yield {"url": url, "db": db, "tokens": tokens, "log": tmp / "service.log"}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def srs(service):
    """A clean database per test (tokens kept) and a REST driver."""
    con = sqlite3.connect(service["db"])
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'") if r[0] not in ("actor_tokens", "alembic_version", "sqlite_sequence")]
    for t in tables:
        con.execute(f"delete from {t}")
    con.commit()
    con.close()
    return Srs(service)


class Srs:
    def __init__(self, service):
        self.url = service["url"]
        self.tokens = service["tokens"]

    def as_(self, who: str) -> httpx.Client:
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {self.tokens[who]}"}, timeout=30)

    def ok(self, r: httpx.Response, status: int = 200):
        assert r.status_code == status, f"{r.status_code}: {r.text[:2000]}"
        return r.json()

    def start(self) -> int:
        body = {"title": "Order events outbox", "slug": "order-events", "requirement": "# Order events\nEmit an event per order change.", "dri": "chandra", "engg": "priya", "product": "maya", "qa": "sam"}
        return self.ok(self.as_("chandra").post("/api/initiatives", json=body), 201)["initiative"]["id"]

    def register_repo(self, clone_url: str, test_command: str = "sh check.sh", name: str = "example/orders"):
        op = {"type": "repository", "fields": {"name": name, "default_branch": "main", "clone_url": clone_url, "test_command": test_command, "junit_path": "reports/junit.xml", "templates": ["python-service"], "owners": ["priya"], "state": "active"}}
        return self.ok(self.as_("priya").post("/api/global/records", json={"ops": [op]}))

    def record(self, iid: int, ref: str) -> dict:
        return self.ok(self.as_("chandra").get(f"/api/initiatives/{iid}/records/{ref}"))

    def write(self, iid: int, ops, who="chandra", batch=None):
        return self.ok(self.as_(who).post(f"/api/initiatives/{iid}/records", json={"ops": ops, "batch_id": batch}))

    def next_work(self, kind: str, who="runner"):
        return self.ok(self.as_(who).get("/api/next-work", params={"kind": kind}))["items"]

    def junit(self, iid: int, task: str, sha: str, failing: bool):
        bad = '<failure message="boom">AssertionError</failure>' if failing else ""
        xml = f'<testsuite><testcase classname="t" name="test_AC_1_outbox_row"/><testcase classname="t" name="test_AC_2_relay">{bad}</testcase><testcase classname="t" name="test_AC_3_key"/></testsuite>'
        body = {"task": task, "sha": sha, "level": "integration", "run_url": f"https://ci.example.com/runs/{sha[:7]}-{int(failing)}", "junit_xml": xml}
        return self.ok(self.as_("ci").post(f"/api/initiatives/{iid}/test-runs/junit", json=body), 201)


def git(*args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def bare_repo(tmp_path):
    """A bare 'GitHub' repository with a main branch: README, CLAUDE.md, check.sh."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    (seed / "README.md").write_text("# orders\n")
    (seed / "CLAUDE.md").write_text("House rules: small commits.\n")
    (seed / "check.sh").write_text("test -f orders/relay.py\n")
    git("add", "-A", cwd=seed)
    git("-c", "user.name=seed", "-c", "user.email=seed@example.com", "commit", "-q", "-m", "seed", cwd=seed)
    bare = tmp_path / "orders.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


sys.path.insert(0, str(ROOT))
