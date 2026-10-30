"""The runner's own calls to the record service (REST, bearer agent token). The agent inside
a skill talks to the same service over MCP with the same token; the runner uses REST for the
loop (next_work, leases) and for the records it guarantees (pr_url / pr_sha, attempt counts)."""

import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx


class SrsError(Exception):
    def __init__(self, status: int, message: str, data: Any = None):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.data = data


def batch_id(*parts: Any) -> str:
    """Deterministic, so a crashed-and-retried job replays its write instead of doubling it."""
    return "rn:" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


class SrsClient:
    def __init__(self, base_url: str, token: str, transport: Optional[httpx.AsyncBaseTransport] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kw) -> Any:
        r = await self._client.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {"title": r.text[:500]}
            raise SrsError(r.status_code, body.get("detail") or body.get("title") or r.reason_phrase, body)
        return r.json() if r.content else None

    # ── the loop ─────────────────────────────────────────────────────────

    async def next_work(self, kind: str, limit: int = 10, initiative_id: Optional[int] = None) -> List[dict]:
        path = f"/api/initiatives/{initiative_id}/next-work" if initiative_id else "/api/next-work"
        out = await self._call("GET", path, params={"kind": kind, "limit": limit})
        return out.get("items", [])

    async def claim(self, key: str, ttl_min: int) -> Optional[dict]:
        """The lease, or None when someone else holds it (409)."""
        try:
            return await self._call("POST", "/api/leases/claim", json={"item_key": key, "ttl_min": ttl_min})
        except SrsError as e:
            if e.status == 409:
                return None
            raise

    async def heartbeat(self, key: str, ttl_min: int) -> dict:
        return await self._call("POST", f"/api/leases/{quote(key, safe=':')}/heartbeat", json={"ttl_min": ttl_min})

    async def release(self, key: str) -> dict:
        return await self._call("DELETE", f"/api/leases/{quote(key, safe=':')}")

    # ── reads ────────────────────────────────────────────────────────────

    async def record(self, initiative_id: int, ref: str) -> dict:
        return await self._call("GET", f"/api/initiatives/{initiative_id}/records/{ref}")

    async def records(self, initiative_id: int, type_: Optional[str] = None) -> List[dict]:
        return await self._call("GET", f"/api/initiatives/{initiative_id}/records", params={"type": type_} if type_ else None)

    async def state(self, initiative_id: int) -> dict:
        return await self._call("GET", f"/api/initiatives/{initiative_id}")

    async def repo(self, name: str) -> Optional[dict]:
        try:
            return await self._call("GET", f"/api/repos/{name}")
        except SrsError as e:
            if e.status == 404:
                return None
            raise

    async def drift_markdown(self, initiative_id: int, task: str) -> str:
        r = await self._client.get(f"/api/initiatives/{initiative_id}/drift", params={"task": task, "format": "md"})
        return r.text if r.status_code == 200 else ""

    # ── writes ───────────────────────────────────────────────────────────

    async def write(self, initiative_id: int, ops: List[Dict], batch: str, agent: str) -> dict:
        return await self._call("POST", f"/api/initiatives/{initiative_id}/records", json={"ops": ops, "batch_id": batch, "agent": agent})

    async def update(self, initiative_id: int, ref: str, fields: Dict, batch: str, agent: str, note: str = "") -> dict:
        """Update one record at its current rev (base_rev: the service refuses an agent edit
        of a field someone else set in the last 15 minutes without it). `batch` is a seed
        (the work item key + sha); the batch id adds the record's rev."""
        rec = await self.record(initiative_id, ref)
        changed = {k: v for k, v in fields.items() if (rec.get("fields") or {}).get(k) != v}
        if not changed:
            return {"ok": True, "unchanged": True}
        op = {"ref": ref, "fields": changed, "base_rev": rec["rev"]}
        if note:
            op["note"] = note
        # the rev is part of the batch id: a retry after a crash finds the fields already set
        # (unchanged above) or replays the same batch, never a different one under one id
        return await self.write(initiative_id, [op], batch_id(batch, ref, rec["rev"]), agent)
