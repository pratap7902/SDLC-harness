"""GitHub App auth and the few REST calls the runner makes (GitHub REST API v3).

App JWT (RS256: iss = app id, iat = now − 60 s, exp = now + 9 min) → installation access
token, scoped to the ONE repository the job touches (`repositories: [name]`) and to
contents:write + pull_requests:write. Tokens live in memory only (never on disk, never in a
git config) and are reused until 5 minutes before they expire."""

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

API_VERSION = "2022-11-28"


class GithubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


def app_jwt(app_id: str, private_key_pem: str, now: Optional[int] = None) -> str:
    import jwt  # PyJWT[crypto]

    now = int(now if now is not None else time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 9 * 60, "iss": str(app_id)}, private_key_pem, algorithm="RS256")


def split_repo(name: str) -> Tuple[str, str]:
    owner, _, repo = name.strip().removesuffix(".git").partition("/")
    if not owner or not repo or "/" in repo:
        raise ValueError(f"repo: owner/name, got {name!r}")
    return owner, repo


@dataclass
class InstallationToken:
    token: str
    expires_at: float  # epoch seconds


@dataclass
class PullRequest:
    number: int
    html_url: str
    head_sha: str
    state: str  # open | closed
    draft: bool
    merged: bool

    @property
    def pr_state(self) -> str:
        if self.merged:
            return "merged"
        if self.state == "closed":
            return "closed"
        return "draft" if self.draft else "open"

    @classmethod
    def from_json(cls, d: dict) -> "PullRequest":
        return cls(
            number=d["number"],
            html_url=d.get("html_url", ""),
            head_sha=(d.get("head") or {}).get("sha", ""),
            state=d.get("state", "open"),
            draft=bool(d.get("draft")),
            merged=bool(d.get("merged") or d.get("merged_at")),
        )


class GithubApp:
    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        api_url: str = "https://api.github.com",
        installation_id: str = "",
        app_slug: str = "",
        bot_user_id: str = "",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.app_id = app_id
        self._key = private_key_pem
        self.api_url = api_url.rstrip("/")
        self.installation_id = installation_id
        self.app_slug = app_slug
        self.bot_user_id = bot_user_id
        self._http = httpx.AsyncClient(base_url=self.api_url, transport=transport, timeout=30.0)
        self._tokens: Dict[str, InstallationToken] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self, bearer: str) -> dict:
        return {"Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}

    async def _req(self, method: str, path: str, bearer: str, **kw) -> httpx.Response:
        r = await self._http.request(method, path, headers=self._headers(bearer), **kw)
        if r.status_code >= 400 and r.status_code != 404:
            raise GithubError(r.status_code, r.text[:300])
        return r

    # ── auth ─────────────────────────────────────────────────────────────

    async def _installation_for(self, repo: str) -> str:
        if self.installation_id:
            return self.installation_id
        owner, name = split_repo(repo)
        r = await self._req("GET", f"/repos/{owner}/{name}/installation", app_jwt(self.app_id, self._key))
        if r.status_code == 404:
            raise GithubError(404, f"the GitHub App is not installed on {repo}")
        return str(r.json()["id"])

    async def token(self, repo: str) -> str:
        """An installation token for exactly this repository."""
        cached = self._tokens.get(repo)
        if cached and cached.expires_at - time.time() > 300:
            return cached.token
        installation = await self._installation_for(repo)
        _, name = split_repo(repo)
        r = await self._req(
            "POST",
            f"/app/installations/{installation}/access_tokens",
            app_jwt(self.app_id, self._key),
            json={"repositories": [name], "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"}},
        )
        body = r.json()
        expires = body.get("expires_at") or ""
        try:
            from datetime import datetime

            exp = datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp()
        except ValueError:
            exp = time.time() + 3000
        self._tokens[repo] = InstallationToken(body["token"], exp)
        return body["token"]

    async def bot_identity(self, repo: str) -> Tuple[str, str]:
        """(name, email) commits are made as: `<slug>[bot]` and its noreply address, so
        GitHub attributes them to the App."""
        slug = self.app_slug or "sdlc-harness"
        name = f"{slug}[bot]"
        if not self.bot_user_id:
            r = await self._req("GET", f"/users/{name}", await self.token(repo))
            if r.status_code == 200:
                self.bot_user_id = str(r.json().get("id", ""))
        email = f"{self.bot_user_id}+{name}@users.noreply.github.com" if self.bot_user_id else f"{name}@users.noreply.github.com"
        return name, email

    # ── pull requests ────────────────────────────────────────────────────

    async def find_pr(self, repo: str, branch: str) -> Optional[PullRequest]:
        owner, name = split_repo(repo)
        r = await self._req("GET", f"/repos/{owner}/{name}/pulls", await self.token(repo), params={"head": f"{owner}:{branch}", "state": "all", "per_page": 10})
        rows = r.json() if r.status_code == 200 else []
        open_ = [p for p in rows if p.get("state") == "open"]
        pick = open_[0] if open_ else (rows[0] if rows else None)
        return PullRequest.from_json(pick) if pick else None

    async def get_pr(self, repo: str, number: int) -> Optional[PullRequest]:
        owner, name = split_repo(repo)
        r = await self._req("GET", f"/repos/{owner}/{name}/pulls/{number}", await self.token(repo))
        return PullRequest.from_json(r.json()) if r.status_code == 200 else None

    async def open_or_update_pr(self, repo: str, branch: str, base: str, title: str, body: str, draft: bool = False) -> PullRequest:
        """Idempotent: an open PR for the branch is updated (title, body), else one is opened."""
        owner, name = split_repo(repo)
        tok = await self.token(repo)
        existing = await self.find_pr(repo, branch)
        if existing and existing.state == "open":
            r = await self._req("PATCH", f"/repos/{owner}/{name}/pulls/{existing.number}", tok, json={"title": title, "body": body})
            return PullRequest.from_json(r.json())
        r = await self._req("POST", f"/repos/{owner}/{name}/pulls", tok, json={"title": title, "head": branch, "base": base, "body": body, "draft": draft})
        if r.status_code == 404:
            raise GithubError(404, f"cannot open a PR on {repo}")
        return PullRequest.from_json(r.json())
