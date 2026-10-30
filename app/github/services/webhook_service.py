"""GitHub → task PR state. A verified delivery (X-Hub-Signature-256) for `pull_request` or
`push` updates the matching task's pr_url / pr_state / pr_sha through RecordService.write as
the integration actor `github` (kind `system`). It cannot write a human field (an approval, a
gap answer). Leases serialise agents only, so GitHub's state lands even while a runner holds
the task; should a write ever be refused for a lease, the delivery is recorded as deferred.

Because GATE_PR's engg approval pins `at_sha`, a new head sha written here makes that
approval STALE and the deploy guard NO-GO — nobody flips a bit.

Which task a PR belongs to, in order:
  1. its head branch `harness/<initiative-id>-<task-ref>` (what the runner pushes),
  2. a marker in the PR body: `srs-task: <initiative-id>/<task-ref>`,
  3. a task whose pr_url is this PR's html_url."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.utils.actor import Actor
from app.initiatives.services.record_service import RecordService, parse_op
from config.settings import settings

GITHUB = Actor(principal="github", kind="system", agent="webhook", via="api")
MARKER_RE = re.compile(r"srs-task:\s*(\d+)\s*/\s*(T-\d+)", re.IGNORECASE)
ZERO_SHA = "0" * 40
PR_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review", "converted_to_draft", "closed", "edited"}


def signature_ok(secret: str, body: bytes, header: Optional[str]) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def branch_task(branch: str) -> Optional[Tuple[int, str]]:
    prefix = settings.github.HARNESS_BRANCH_PREFIX
    if not branch or not branch.startswith(prefix):
        return None
    m = re.fullmatch(r"(\d+)-(T-\d+)", branch[len(prefix):])
    return (int(m.group(1)), m.group(2)) if m else None


@dataclass
class Outcome:
    status: str  # updated | unchanged | ignored | deferred | rejected
    detail: str = ""
    initiative_id: Optional[int] = None
    task: Optional[str] = None
    fields: Optional[Dict] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class WebhookService:
    def __init__(self, records: RecordService):
        self.records = records

    # ── routing ─────────────────────────────────────────────────────────

    def handle(self, event: str, delivery: str, payload: dict) -> Outcome:
        if event == "ping":
            return Outcome("ignored", "pong")
        if event == "pull_request":
            return self._pull_request(delivery, payload)
        if event == "push":
            return self._push(delivery, payload)
        return Outcome("ignored", f"event {event!r} is not used")

    def _find(self, pr: dict) -> Optional[Tuple[int, str]]:
        found = branch_task(((pr.get("head") or {}).get("ref")) or "")
        if found:
            return found
        m = MARKER_RE.search(pr.get("body") or "")
        if m:
            return int(m.group(1)), m.group(2)
        url = pr.get("html_url") or ""
        if url:
            for i in self.records.initiatives.list_ordered():
                g = self.records.graph(i, derive=False)
                for t in g.of_type("task"):
                    if g.f(t, "pr_url") == url:
                        return i.id, t.ref
        return None

    # ── events ──────────────────────────────────────────────────────────

    def _pull_request(self, delivery: str, payload: dict) -> Outcome:
        action = payload.get("action") or ""
        pr = payload.get("pull_request") or {}
        if action not in PR_ACTIONS:
            return Outcome("ignored", f"pull_request.{action} is not used")
        target = self._find(pr)
        if target is None:
            return Outcome("ignored", "no task for this PR (branch, srs-task marker or pr_url)")
        sha = (pr.get("head") or {}).get("sha") or ""
        if action == "closed":
            state = "merged" if pr.get("merged") else "closed"
        else:
            state = "draft" if pr.get("draft") else "open"
        fields = {"pr_url": pr.get("html_url") or "", "pr_state": state, "pr_sha": sha}
        return self._write(target, fields, delivery, f"github pull_request.{action} #{pr.get('number')}")

    def _push(self, delivery: str, payload: dict) -> Outcome:
        ref = payload.get("ref") or ""
        after = payload.get("after") or ""
        if not ref.startswith("refs/heads/") or not after or after == ZERO_SHA:
            return Outcome("ignored", "not a branch update")
        target = branch_task(ref[len("refs/heads/"):])
        if target is None:
            return Outcome("ignored", "not a harness branch")
        try:
            g = self.records.graph(self.records.initiative(target[0]))
        except Exception:  # noqa: BLE001 — an unknown initiative is not GitHub's problem
            return Outcome("ignored", f"no initiative {target[0]}")
        task = g.get(target[1])
        if task is None or task.type != "task":
            return Outcome("ignored", f"no task {target[1]}")
        if g.f(task, "pr_state") not in ("draft", "open", "approved"):
            return Outcome("ignored", "no open PR recorded for the task yet (pull_request.opened sets it)")
        return self._write(target, {"pr_sha": after}, delivery, f"github push {after[:7]}")

    # ── the write ───────────────────────────────────────────────────────

    def _write(self, target: Tuple[int, str], fields: Dict, delivery: str, note: str) -> Outcome:
        initiative_id, ref = target
        try:
            initiative = self.records.initiative(initiative_id)
        except Exception:  # noqa: BLE001
            return Outcome("ignored", f"no initiative {initiative_id}", initiative_id, ref)
        g = self.records.graph(initiative)
        task = g.get(ref)
        if task is None or task.type != "task":
            return Outcome("ignored", f"no task {ref}", initiative_id, ref)
        changed = {k: v for k, v in fields.items() if v and g.f(task, k) != v}
        if not changed:
            return Outcome("unchanged", "", initiative_id, ref)
        if "pr_state" in changed or g.f(task, "pr_state") in (None, "", "none"):
            changed.setdefault("pr_url", fields.get("pr_url") or g.f(task, "pr_url"))
            changed.setdefault("pr_sha", fields.get("pr_sha") or g.f(task, "pr_sha"))
        op = parse_op({"ref": ref, "fields": changed, "note": note})
        batch_id = f"gh:{delivery}"[:64] if delivery else None
        result = self.records.write(initiative.id, [op], GITHUB, batch_id)
        if not result.ok:
            errors: List[str] = [e for r in result.results for e in r.errors]
            if any("leased by" in e for e in errors):
                self.records.events.add("github_sync_deferred", initiative.id, ref, GITHUB.name, "", {"fields": changed, "delivery": delivery})
                self.records.db.commit()
                return Outcome("deferred", "; ".join(errors), initiative_id, ref, changed)
            return Outcome("rejected", "; ".join(errors), initiative_id, ref, changed)
        return Outcome("updated", note, initiative_id, ref, changed)
