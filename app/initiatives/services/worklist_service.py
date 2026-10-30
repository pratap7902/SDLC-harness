"""The worklist is the pipeline's cursor: the union of every queue, each item with a key a
runner can lease. `next_work` filters it to what a caller may take now (not leased by
someone else), in priority order, each with a context bundle."""

from datetime import timedelta
from typing import Annotated, List, Optional

from fastapi import Depends

from app.core.utils.time import iso, utcnow
from app.exceptions import ConflictException, NotFoundException, ValidationException
from app.initiatives.repositories.lease_repository import LeaseRepository
from app.initiatives.services.gate_rules import GateRules, catalog_state
from app.initiatives.services.inbox_service import InboxService
from app.initiatives.services.record_graph import RecordGraph
from app.initiatives.services.record_service import GLOBAL_SLUG, RecordService
from app.initiatives.services.status_rules import LIVE_AC
from app.initiatives.services.views import record_json, review_item_json
from config.settings import settings

KINDS = ("review", "gap", "decision", "approval", "draft", "plan", "tests", "task", "pr_review", "promotion", "manual_ac")
PRIORITY = {"review": 10, "gap": 20, "decision": 20, "approval": 25, "manual_ac": 28, "draft": 30, "plan": 40, "tests": 50, "task": 60, "pr_review": 65, "promotion": 90}
PHASE_OF_KIND = {"draft": "draft", "plan": "plan", "task": "build", "tests": "build", "pr_review": "build", "review": "draft"}


class WorklistService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records
        self.bp = records.bp
        self.leases = LeaseRepository(records.db)

    # ── items ────────────────────────────────────────────────────────────

    def items(self, g: RecordGraph) -> List[dict]:
        slug = g.initiative.slug
        out: List[dict] = []
        phase = g.get("initiative").status if g.get("initiative") is not None else "UNASSIGNED"

        def add(kind, ref, title, why, lane="agent", person=None, **extra):
            key = f"{kind}:{g.initiative.id}" + (f":{ref}" if ref else "")
            out.append(
                {
                    "key": key,
                    "kind": kind,
                    "lane": lane,
                    "initiative_id": g.initiative.id,
                    "initiative": slug,
                    "ref": ref,
                    "title": title,
                    "why": why,
                    "person": person,
                    "priority": PRIORITY[kind],
                    **extra,
                }
            )

        if phase in ("UNASSIGNED", "CLOSED"):
            return out
        for item in g.open_review_items:
            advised = item.judged_by == "agent"
            add(
                "review",
                str(item.id),
                f"{item.target_ref} ← {item.cause_ref}",
                f"agent says it holds ({item.note}) — waiting on {item.route_to or 'a human'} to uphold"
                if advised
                else f"{item.cause_ref} moved ({item.what_moved}) — revise {item.target_ref}, or say why it still holds",
                lane="human" if advised else "agent",
                person=item.route_to,
                target=item.target_ref,
                cause=item.cause_ref,
                review_item_id=item.id,
            )
        # the human lane, as the inbox routes it
        for x in InboxService(self.records).items_for(g):
            kind = x["kind"]
            if kind == "review_item":
                continue
            add(kind, x["ref"], x.get("title", ""), f"waiting on {x['person'] or 'an unassigned ' + x['route']['role']}", lane="human", person=x["person"], overdue=x["overdue"], sla_hours=x["sla_hours"])
        draft = g.get("draft")
        rules = GateRules(self.bp)
        if phase == "DRAFT":
            if draft is None:
                add("draft", None, "Write the draft", "no draft yet: problem, hld, lld, test_strategy, decisions, ACs")
            elif draft.status in ("DRAFTING", "REOPENED"):
                failing = rules.preconditions(g, "GATE_DRAFT")
                why = "; ".join(f"{r.name} ({', '.join(r.failing)})" if r.failing else r.name for r in failing)
                add("draft", None, f"Draft is {draft.status}", why or "ready to submit: set submitted_rev")
            elif draft.status == "IN_REVIEW":
                failing = rules.preconditions(g, "GATE_DRAFT")
                if failing:
                    add("draft", None, "Draft submitted but not approvable", "; ".join(r.name for r in failing))
        elif draft is not None and draft.status == "REOPENED":
            add("draft", None, "Draft REOPENED — unexplained drift", "explain each change (because) or ask the DRI to re-approve")
        if phase == "PLAN":
            covered = {ac for t in g.of_type("task") for ac in g.f(t, "covers") or []}
            missing = [a.ref for a in g.of_type("acceptance_criterion") if a.status in LIVE_AC and a.ref not in covered]
            add("plan", None, "Plan tasks", f"ACs not covered by a task: {', '.join(missing) or 'none'}" if g.of_type("task") else "no tasks yet")
        if phase in ("PLAN", "BUILD", "VALIDATE"):
            for t in g.of_type("task"):
                if t.status == "READY":
                    add("task", t.ref, t.title, f"implement {', '.join(g.f(t, 'implements') or [])}; cover {', '.join(g.f(t, 'covers') or [])}")
                elif t.status == "STUCK":
                    add("task", t.ref, t.title, "STUCK — hand off to a human", lane="human", person=g.person_for("engg", t.ref))
                elif t.status == "IN_REVIEW":
                    rework = self._rework(g, t)
                    if rework:
                        add("task", t.ref, t.title, rework["why"], rework=rework["cause"], rework_refs=rework["refs"])
                    elif g.f(t, "pr_sha") and g.f(t, "reviewed_sha") != g.f(t, "pr_sha"):
                        sha = g.f(t, "pr_sha")
                        add("pr_review", t.ref, f"Review {t.ref} @ {sha[:7]}", f"AI first-pass review of {g.f(t, 'pr_url')} at {sha[:7]}", sha=sha)
                tested = {row.get("ac") for run in g.of_type("test_run") for row in g.f(run, "covers") or []}
                untested = [ac for ac in g.f(t, "covers") or [] if ac not in tested and g.f(ac, "manual") != "yes"]
                if t.status in ("IN_PROGRESS", "IN_REVIEW") and untested:
                    add("tests", t.ref, f"Tests for {t.ref}", f"no test run row for {', '.join(untested)}")
        return out

    @staticmethod
    def _rework(g: RecordGraph, t) -> Optional[dict]:
        """A PR at its head sha that the agent lane must work again: a red/errored test run
        at that sha (cause `ci`), or an OPEN blocker/major finding bound to that sha (cause
        `review`). Evidence at an older sha does not count — a new push answers it."""
        sha = g.f(t, "pr_sha")
        if not sha:
            return None
        runs = [r for r in g.of_type("test_run") if g.f(r, "at_sha") == sha and t.ref in (g.f(r, "task") or [])]
        if runs:
            latest = max(runs, key=lambda r: (g.f(r, "run_on") or "", r.ref))
            if g.f(latest, "result") in ("RED", "ERROR"):
                return {"cause": "ci", "refs": [latest.ref], "why": f"tests {g.f(latest, 'result')} at {sha[:7]} ({latest.ref}) — fix and push"}
        findings = [
            f.ref
            for f in g.of_type("finding")
            if f.status == "OPEN" and g.f(f, "severity") in ("blocker", "major") and t.ref in (g.f(f, "target") or []) and g.f(f, "at_sha") == sha
        ]
        if findings:
            return {"cause": "review", "refs": findings, "why": f"review findings at {sha[:7]}: {', '.join(findings)} — address and push"}
        return None

    def worklist(self, slug: str) -> dict:
        g = self.records.graph(self.records.initiative(slug))
        items = self._with_leases(self.items(g))
        groups = {}
        for x in items:
            groups.setdefault(x["kind"], []).append(x)
        return {"initiative_id": g.initiative.id, "initiative": g.initiative.slug, "count": len(items), "groups": groups, "items": items}

    def next_work(self, slug: Optional[str], kind: Optional[str], person: Optional[str], holder: str, limit: int = 10) -> dict:
        if kind and kind not in KINDS:
            raise ValidationException(message=f"kind: one of {', '.join(KINDS)}")
        initiatives = [self.records.initiative(slug)] if slug else self.records.initiatives.list_ordered()
        picked: List[dict] = []
        for i in initiatives:
            g = self.records.graph(i)
            for x in self._with_leases(self.items(g)):
                if kind and x["kind"] != kind:
                    continue
                if person and x.get("person") != person:
                    continue
                lease = x["lease"]
                if lease and lease["holder"] != holder:
                    continue
                x["context"] = self._context(g, x)
                picked.append(x)
        if (not slug and not kind) or kind == "promotion":
            picked += self._promotions(person)
        picked.sort(key=lambda x: (x["priority"], x["key"]))
        return {"count": len(picked), "items": picked[:limit]}

    def _promotions(self, person) -> List[dict]:
        g = self.records.graph(self.records.initiative(GLOBAL_SLUG))
        return [
            {
                "key": f"promotion:0:{r.ref}",
                "kind": "promotion",
                "lane": "human",
                "initiative_id": 0,
                "initiative": GLOBAL_SLUG,
                "ref": r.ref,
                "title": r.title,
                "why": "a learning waits for a human to promote it",
                "person": person,
                "priority": PRIORITY["promotion"],
                "lease": None,
                "context": {"record": record_json(r, g)},
            }
            for r in g.of_type("learning")
            if r.status == "DRAFT"
        ]

    def _context(self, g: RecordGraph, item: dict) -> dict:
        ref = item.get("target") or item.get("ref")
        if item["kind"] == "draft":
            ref = "draft"
        record = g.get(ref) if ref else None
        ctx: dict = {}
        if record is not None:
            ctx["record"] = record_json(record, g, detail=True)
            spec = self.bp.types[record.type]
            cites = {}
            for f in spec.refs_fields():
                for r in g.f(record, f.name) or []:
                    target = g.get(r)
                    if target is not None:
                        cites[r] = {"type": target.type, "title": target.title, "status": target.status, "line": g.f(target, self.bp.types[target.type].line) if self.bp.types[target.type].line else None}
            ctx["cites"] = cites
            ctx["review_items"] = [review_item_json(i) for i in g.open_review_items if i.target_ref == record.ref]
        phase = PHASE_OF_KIND.get(item["kind"])
        if phase:
            ctx["catalog"] = catalog_state(g, phase)
        if item["kind"] in ("task", "tests", "pr_review") and g.current_baseline() is not None:
            ctx["drift"] = g.drift(task=item["ref"]).summary()
        return ctx

    def _with_leases(self, items: List[dict]) -> List[dict]:
        now = utcnow()
        for x in items:
            lease = self.leases.get(x["key"])
            x["lease"] = (
                {"holder": lease.holder, "expires_at": iso(lease.expires_at), "acquired_at": iso(lease.acquired_at)}
                if lease is not None and lease.expires_at > now
                else None
            )
        return items

    # ── leases ───────────────────────────────────────────────────────────

    def claim(self, key: str, holder: str, ttl_min: Optional[int] = None) -> dict:
        if not holder:
            raise ValidationException(message="Who is claiming? Send X-Actor.")
        if not key or ":" not in key:
            raise ValidationException(message="item_key: like task:<initiative id>:T-3 (from next_work)")
        ttl = int(ttl_min or settings.app.LEASE_DEFAULT_TTL_MIN)
        if ttl < 1 or ttl > 240:
            raise ValidationException(message="ttl_min: 1–240")
        now = utcnow()
        if not self.leases.try_claim(key, holder, now, now + timedelta(minutes=ttl)):
            lease = self.leases.get(key)
            raise ConflictException(
                message=f"{key} is held by {lease.holder} until {iso(lease.expires_at)}",
                error_code="LEASE_HELD",
                error_data={"holder": lease.holder, "expires_at": iso(lease.expires_at)},
            )
        self.records.events.add("lease_claimed", 0, key, holder, "", {"ttl_min": ttl})
        self.records.db.commit()
        return self._lease_json(key)

    def heartbeat(self, key: str, holder: str, ttl_min: Optional[int] = None) -> dict:
        ttl = int(ttl_min or settings.app.LEASE_DEFAULT_TTL_MIN)
        now = utcnow()
        if not self.leases.heartbeat(key, holder, now, now + timedelta(minutes=ttl)):
            raise NotFoundException(message=f"{holder} holds no live lease on {key} — claim it again")
        self.records.db.commit()
        return self._lease_json(key)

    def release(self, key: str, holder: str) -> dict:
        released = self.leases.release(key, holder)
        if released:
            self.records.events.add("lease_released", 0, key, holder, "", {})
        self.records.db.commit()
        return {"item_key": key, "released": released}

    def _lease_json(self, key: str) -> dict:
        lease = self.leases.get(key)
        return {
            "item_key": key,
            "holder": lease.holder,
            "acquired_at": iso(lease.acquired_at),
            "heartbeat_at": iso(lease.heartbeat_at),
            "expires_at": iso(lease.expires_at),
        }
