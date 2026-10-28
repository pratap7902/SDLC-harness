"""A thin REST driver for tests: who calls (person + kind) is explicit on every call."""

import itertools
from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

_batch = itertools.count(1)


class Api:
    def __init__(self, app):
        self.app = app

    def as_(self, person: str, kind: str = "human") -> TestClient:
        return TestClient(self.app, headers={"X-Actor": person, "X-Actor-Kind": kind})

    def agent(self) -> TestClient:
        return self.as_("runner-sdk", "agent")

    # ── calls that must succeed ─────────────────────────────────────────

    def ok(self, response, status: int = 200) -> Any:
        assert response.status_code == status, f"{response.status_code}: {response.text[:2000]}"
        return response.json()

    def start(self, slug="order-events", title="Order events outbox", **extra) -> dict:
        body = {
            "title": title,
            "slug": slug,
            "requirement": "# Order events\nEmit an event for every order state change so downstream "
            "services stop polling the orders table.",
            "work_item_url": "https://dev.azure.com/acme/orders/_workitems/edit/4211",
            "dri": "chandra",
            "engg": "priya",
            "product": "maya",
            "qa": "sam",
            **extra,
        }
        return self.ok(self.as_("chandra").post("/api/initiatives", json=body), 201)

    def write(self, slug: str, ops: List[Dict], who: Optional[TestClient] = None, batch_id: Optional[str] = None, expect: int = 200) -> dict:
        body = {"ops": ops, "batch_id": batch_id or f"b-{next(_batch)}"}
        if who is None:
            who, body["agent"] = self.agent(), "draft-skill"
        r = who.post(f"/api/initiatives/{slug}/records", json=body)
        if expect != 200:
            assert r.status_code == expect, f"{r.status_code}: {r.text[:2000]}"
            return r.json()
        return self.ok(r)

    def rejected(self, slug: str, ops: List[Dict], who: Optional[TestClient] = None) -> List[str]:
        """Write expected to be refused: returns every op error."""
        out = self.write(slug, ops, who, expect=422)
        return [e for r in out["error_data"]["results"] for e in r["errors"]]

    def get(self, path: str, **params) -> Any:
        return self.ok(self.as_("chandra").get(path, params=params))

    def answer(self, slug, ref, answer="", choice=None, person="priya") -> dict:
        return self.ok(self.as_(person).post(f"/api/initiatives/{slug}/gaps/{ref}/answer", json={"answer": answer, "choice": choice}))

    def approve(self, slug, target, role, person, at_sha=None, expect=201) -> dict:
        r = self.as_(person).post(f"/api/initiatives/{slug}/approvals", json={"target": target, "role": role, "at_sha": at_sha})
        assert r.status_code == expect, f"{r.status_code}: {r.text[:2000]}"
        return r.json()

    def state(self, slug) -> dict:
        return self.get(f"/api/initiatives/{slug}")

    def drift(self, slug, task=None, **params) -> dict:
        if task:
            params["task"] = task
        return self.get(f"/api/initiatives/{slug}/drift", **params)

    def record(self, slug, ref) -> dict:
        return self.get(f"/api/initiatives/{slug}/records/{ref}")
