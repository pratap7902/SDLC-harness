"""The overview: everything the Features list shows, in one read. Per initiative its phase,
people, the next open human item, PR approvals (approved / total, stale), drift, GATE_DRAFT
state, the latest activity, and the agent lane (queued / leased); across initiatives the
decisions waiting on people and the caller's own PR approvals. Built from the same services
the per-initiative endpoints use (inbox routing, worklist, gates, drift) — nothing new is
derived here, it is only gathered."""

from typing import Annotated, List, Optional

from fastapi import Depends

from app.core.utils.time import iso, utcnow
from app.initiatives.services.gate_rules import GateRules
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.record_graph import RecordGraph
from app.initiatives.services.record_service import RecordService
from app.initiatives.services.views import initiative_json
from app.initiatives.services.worklist_service import WorklistService

ROLES = ("dri", "engg", "product", "design", "qa")
KIND_LABEL = {"gap": "gap", "decision": "decision", "approval": "approval", "review_item": "review item", "manual_ac": "manual criterion"}


def blocking(item: dict) -> bool:
    if item["kind"] == "gap":
        return item.get("level") != "SHOULD" and bool(item.get("blocks"))
    if item["kind"] == "decision":
        return item.get("level") == "MUST"
    return item["kind"] in ("approval", "manual_ac")


def short_label(item: dict) -> str:
    """`G-2 · gap`, `review T-1`, `approve draft`, `D-12 still holds?`."""
    kind = item["kind"]
    if kind == "approval":
        return "approve the draft" if item.get("target") == "draft" else f"review {item.get('target')}"
    if kind == "review_item":
        return f"does {item.get('target')} still hold?"
    if kind == "manual_ac":
        return f"sign {item['ref']}"
    return f"{item['ref']} · {KIND_LABEL[kind]}"


def sort_key(person: Optional[str]):
    """Yours first, then what blocks work, then overdue, then the inbox's own priority."""
    return lambda x: (x["person"] != person, not blocking(x), not x["overdue"], x["priority"], x["since"] or "")


class OverviewService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records
        self.inbox = InboxService(records)
        self.worklist = WorklistService(records)
        self.rules = GateRules(records.bp)

    def _gate_draft(self, g: RecordGraph) -> dict:
        gate = g.gate("GATE_DRAFT")
        draft = g.get("draft")
        if gate.status == "PASSED":
            state = "approved"
        elif draft is not None and draft.status == "REOPENED":
            state = "reopened"
        elif draft is None or draft.status == "DRAFTING" and not g.of_type("decision"):
            state = "drafting"
        elif not self.rules.preconditions(g, "GATE_DRAFT"):
            state = "ready"
        else:
            state = "waiting"
        return {
            "status": gate.status,
            "state": state,
            "failing_rules": [r for r in gate.failing_rules if r != "approval_by_role"],
            "draft_rev": draft.head_rev if draft is not None else None,
            "draft_status": draft.status if draft is not None else None,
        }

    def _prs(self, g: RecordGraph) -> dict:
        tasks = g.of_type("task")
        approved, stale = [], []
        for t in tasks:
            if t.status == "DONE" or g.gate("GATE_PR", task=t.ref).status == "PASSED":
                approved.append(t.ref)
                continue
            mine = [a for a in g.of_type("approval") if t.ref in (g.f(a, "target") or [])]  # approvals of this task
            if mine and all(a.status == "STALE" for a in mine):
                stale.append(t.ref)
        return {
            "total": len(tasks),
            "approved": len(approved),
            "approved_refs": approved,
            "stale": stale,
            "with_pr": sum(1 for t in tasks if g.f(t, "pr_url")),
            "done": sum(1 for t in tasks if t.status == "DONE"),
        }

    def _updated_at(self, initiative_id: int) -> Optional[str]:
        revs = self.records.revisions.list_for_initiative(initiative_id)
        latest = max((r.created_at for r in revs), default=None)
        reviews = [x.resolved_at or x.created_at for x in self.records.reviews.all_for(initiative_id)]
        latest = max([d for d in [latest, *reviews] if d is not None], default=None)
        return iso(latest) if latest else None

    def overview(self, person: Optional[str] = None) -> dict:
        rows: List[dict] = []
        waiting: List[dict] = []
        # Live leases, by initiative: a leased item may leave the queue (a leased task is
        # IN_PROGRESS), so leases are read directly. Keys are `<kind>:<slug>[:<ref>]`.
        leases = {}
        for lease in self.worklist.leases.active(utcnow()):
            parts = lease.item_key.split(":")
            if len(parts) >= 2:
                leases.setdefault(parts[1], []).append({"key": lease.item_key, "kind": parts[0], "ref": parts[2] if len(parts) > 2 else None, "holder": lease.holder})
        for i in self.records.initiatives.list_ordered():
            g = self.records.graph(i)
            items = self.inbox.items_for(g)
            waiting += items
            agent = [x for x in self.worklist.items(g) if x["lane"] == "agent"]
            held = leases.get(i.slug, [])
            held_keys = {h["key"] for h in held}
            people = {}
            for role in ROLES:
                p = g.person_for(role)
                if p:
                    people[role] = p
            baseline = g.current_baseline()
            drift = g.drift() if baseline is not None else None
            nxt = sorted(items, key=sort_key(person))[0] if items else None
            rows.append(
                {
                    **initiative_json(i, g),
                    "dri": people.get("dri"),
                    "engg": people.get("engg"),
                    "people": people,
                    "involved": bool(person) and (person in people.values() or any(x["person"] == person for x in items)),
                    "counts": {
                        "open_gaps": sum(1 for r in g.of_type("gap") if r.status == "OPEN"),
                        "open_decisions": sum(1 for r in g.of_type("decision") if r.status == "OPEN"),
                        "tasks": len(g.of_type("task")),
                        "tasks_done": sum(1 for t in g.of_type("task") if t.status == "DONE"),
                        "open_review_items": len(g.open_review_items),
                        "waiting": len(items),
                    },
                    "next": (
                        {
                            "key": nxt["key"],
                            "kind": nxt["kind"],
                            "ref": nxt["ref"],
                            "person": nxt["person"],
                            "label": short_label(nxt),
                            "title": nxt["title"],
                            "overdue": nxt["overdue"],
                            "due_at": nxt["due_at"],
                        }
                        if nxt
                        else None
                    ),
                    "prs": self._prs(g),
                    "gate_draft": self._gate_draft(g),
                    "baseline": baseline.ref if baseline is not None else None,
                    "drift": drift.summary() if drift is not None else None,
                    "updated_at": self._updated_at(i.id),
                    "agents": {
                        "queued": sum(1 for x in agent if x["key"] not in held_keys),
                        "leased": len(held),
                        "holders": sorted({h["holder"] for h in held}),
                        "working": [{"kind": h["kind"], "ref": h["ref"], "holder": h["holder"]} for h in held]
                        + [{"kind": x["kind"], "ref": x["ref"], "holder": None} for x in agent if x["key"] not in held_keys],
                    },
                }
            )
        waiting.sort(key=sort_key(person))
        decisions = [x for x in waiting if not (x["kind"] == "approval" and x.get("target") != "draft")]
        approvals = [x for x in waiting if x["kind"] == "approval" and x.get("target") != "draft" and person and x["person"] == person]
        return {
            "person": person,
            "summary": {
                "features": len(rows),
                "decisions_waiting": len(decisions),
                "agents_working": sum(1 for r in rows if r["agents"]["queued"] or r["agents"]["leased"]),
                "agents_leased": sum(1 for r in rows if r["agents"]["leased"]),
            },
            "initiatives": rows,
            "waiting": waiting,
            "decisions": decisions,
            "my_pr_approvals": approvals,
        }
