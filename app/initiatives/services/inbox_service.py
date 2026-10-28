"""The human lane (touchpoints 2 and 3, and the approvals of 1): a personal inbox routed by
domain, and the human-only operations — answer a gap, rule a decision, approve, sign a
manual AC, retire an AC, promote a learning. Every one is a RecordService.write with
actor_kind=human; agents get 403 before they get here (REST) and have no MCP tool."""

from datetime import timedelta
from typing import Annotated, List, Optional

from fastapi import Depends

from app.core.utils.actor import Actor, require_human
from app.core.utils.time import iso, utcnow
from app.exceptions import ValidationException
from app.initiatives.schemas.write import WriteOp, WriteResult
from app.initiatives.services.gate_rules import GateRules
from app.initiatives.services.record_graph import RecordGraph
from app.initiatives.services.record_service import GLOBAL_SLUG, RecordService
from app.initiatives.services.routing import Router
from app.initiatives.services.views import record_json

PRIORITY = {"gap": 10, "decision": 10, "approval": 20, "review_item": 30, "manual_ac": 40}


class InboxService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records
        self.bp = records.bp

    # ── the inbox ────────────────────────────────────────────────────────

    def items_for(self, g: RecordGraph) -> List[dict]:
        """Every human item of one initiative, each with the person it routes to."""
        if g.initiative.id == 0 or g.get("initiative") is None or g.get("initiative").status == "CLOSED":
            return []
        lc = self.bp.lifecycle
        router = Router(g)
        now = utcnow()
        slug = g.initiative.slug
        items: List[dict] = []

        def add(kind, ref, route, since, sla_kind, **extra):
            sla = lc.sla_hours(sla_kind)
            age = (now - since).total_seconds() / 3600 if since else 0
            items.append(
                {
                    "key": f"{kind}:{slug}:{ref}",
                    "kind": kind,
                    "initiative": slug,
                    "initiative_title": g.initiative.title,
                    "ref": ref,
                    "route": route.to_dict(),
                    "person": route.person,
                    "since": iso(since),
                    "age_hours": round(age, 1),
                    "sla_hours": sla,
                    "due_at": iso(since + timedelta(hours=sla)) if since else None,
                    "overdue": age > sla,
                    "priority": PRIORITY.get(kind, 50),
                    **extra,
                }
            )

        for gap in g.of_type("gap"):
            if gap.status != "OPEN":
                continue
            add(
                "gap",
                gap.ref,
                router.route(gap),
                gap.created_at,
                "gap",
                title=gap.title,
                record=record_json(gap, g),
                question=g.f(gap, "question", ""),
                context=g.f(gap, "context", ""),
                options=g.f(gap, "options") or [],
                recommendation=g.f(gap, "recommendation"),
                recommendation_why=g.f(gap, "recommendation_why"),
                blocks=g.f(gap, "blocks") or [],
                level=g.f(gap, "level", "MUST"),
            )
        for d in g.of_type("decision"):
            needs_human = (d.status == "OPEN" and (g.f(d, "level") == "MUST" or g.f(d, "escalated") == "yes")) or (
                d.status == "PROVISIONAL" and g.f(d, "escalated") == "yes"
            )
            if not needs_human:
                continue
            add(
                "decision",
                d.ref,
                router.route(d),
                d.created_at,
                "decision",
                title=d.title,
                record=record_json(d, g),
                question=g.f(d, "question", ""),
                options=g.f(d, "options") or [],
                provisional_verdict=g.f(d, "verdict") if d.status == "PROVISIONAL" else None,
                level=g.f(d, "level"),
                blocks=[t.ref for t in g.of_type("task") if d.ref in (g.f(t, "implements") or [])],
            )
        rules = GateRules(self.bp)
        draft = g.get("draft")
        if draft is not None and g.gate("GATE_DRAFT").status != "PASSED" and not rules.preconditions(g, "GATE_DRAFT"):
            add(
                "approval",
                "draft",
                router.for_role("dri"),
                draft.updated_at,
                "approval",
                title=f"Approve the draft of {g.initiative.title} (rev {draft.head_rev})",
                gate="GATE_DRAFT",
                role="dri",
                target="draft",
                draft_status=draft.status,
            )
        for t in g.of_type("task"):
            if g.gate("GATE_PR", task=t.ref).status == "PASSED":
                continue
            if rules.preconditions(g, "GATE_PR", task=t.ref):
                continue
            report = g.drift(task=t.ref)
            stale = [a.ref for a in g.of_type("approval") if t.ref in (g.f(a, "target") or []) and a.status == "STALE"]
            add(
                "approval",
                t.ref,
                router.for_role("engg", t.ref),
                t.updated_at,
                "approval",
                title=f"Review the drift of {t.ref}: {t.title}"
                + (" (your earlier approval went stale)" if stale else ""),
                gate="GATE_PR",
                role="engg",
                target=t.ref,
                pr_url=g.f(t, "pr_url"),
                pr_sha=g.f(t, "pr_sha"),
                drift=report.summary(),
                digest=report.digest,
                stale_approvals=stale,
            )
        for item in g.open_review_items:
            target = g.get(item.target_ref)
            if target is None or not item.route_to:
                continue
            add(
                "review_item",
                str(item.id),
                Router(g).route(target, g.get(item.cause_ref)),
                item.created_at,
                "review_item",
                title=f"{item.target_ref} ← {item.cause_ref}: does it still hold?",
                review_item_id=item.id,
                target=item.target_ref,
                cause=item.cause_ref,
                what_moved=item.what_moved,
            )
            items[-1]["person"] = item.route_to
            items[-1]["route"]["person"] = item.route_to
        for ac in g.of_type("acceptance_criterion"):
            if g.f(ac, "manual") != "yes" or g.f(ac, "signed_by") or ac.status not in ("APPROVED", "ADDED_AFTER_BASELINE"):
                continue
            tasks = [t for t in g.of_type("task") if ac.ref in (g.f(t, "covers") or [])]
            if not any(g.f(t, "pr_state") in ("open", "approved", "merged") for t in tasks):
                continue
            add(
                "manual_ac",
                ac.ref,
                router.for_role("qa"),
                ac.updated_at,
                "manual_ac",
                title=f"Sign manual AC {ac.ref}",
                text=g.f(ac, "text"),
                at_sha=next((g.f(t, "pr_sha") for t in tasks if g.f(t, "pr_sha")), None),
            )
        return items

    def inbox(self, person: str) -> dict:
        items: List[dict] = []
        for i in self.records.initiatives.list_ordered():
            items += [x for x in self.items_for(self.records.graph(i)) if x["person"] == person]
        items.sort(key=lambda x: (not x["overdue"], x["priority"], x["since"] or ""))
        counts = {}
        for x in items:
            counts[x["kind"]] = counts.get(x["kind"], 0) + 1
        return {"person": person, "count": len(items), "overdue": sum(1 for x in items if x["overdue"]), "counts": counts, "items": items}

    def people(self) -> List[dict]:
        people = {}
        for i in self.records.initiatives.list_ordered():
            g = self.records.graph(i)
            for a in g.of_type("assignment"):
                if a.status != "ACTIVE":
                    continue
                p = people.setdefault(g.f(a, "person"), {"person": g.f(a, "person"), "roles": [], "inbox": 0})
                p["roles"].append({"initiative": i.slug, "role": g.f(a, "role")})
            for x in self.items_for(g):
                if x["person"]:
                    people.setdefault(x["person"], {"person": x["person"], "roles": [], "inbox": 0})["inbox"] += 1
        return sorted(people.values(), key=lambda p: p["person"])

    # ── human-only operations ────────────────────────────────────────────

    def _write(self, slug: str, ops: List[WriteOp], actor: Actor) -> WriteResult:
        result = self.records.write(slug, ops, actor)
        if not result.ok:
            errors = [e for r in result.results for e in r.errors]
            raise ValidationException(message="; ".join(errors) or "rejected", error_data=result.to_dict())
        return result

    def answer_gap(self, slug: str, ref: str, answer: str, choice: Optional[str], actor: Actor) -> WriteResult:
        require_human(actor)
        i = self.records.initiative(slug)
        g = self.records.graph(i)
        gap = g.get(ref)
        if gap is None or gap.type != "gap":
            raise ValidationException(message=f"{ref} is not a gap of {slug}")
        if gap.status != "OPEN":
            raise ValidationException(message=f"{ref} is {gap.status} — answered by {g.f(gap, 'answered_by') or '?'}")
        options = {o.get("key"): o for o in g.f(gap, "options") or []}
        if choice and choice not in options:
            raise ValidationException(message=f"choice: '{choice}' is not an option of {ref}; options: {', '.join(options) or 'none'}")
        text = (answer or "").strip() or (options[choice].get("label", choice) if choice else "")
        if not text:
            raise ValidationException(message="answer: required — pick an option or type an answer")
        fields = {"answer": text, "answered_by": actor.principal, "answered_on": iso(utcnow())}
        if choice:
            fields["choice"] = choice
        return self._write(slug, [WriteOp(ref=ref, fields=fields, note="answered in the inbox")], actor)

    def rule_decision(self, slug: str, ref: str, verdict: str, rationale: str, actor: Actor) -> WriteResult:
        require_human(actor)
        i = self.records.initiative(slug)
        g = self.records.graph(i)
        d = g.get(ref)
        if d is None or d.type != "decision":
            raise ValidationException(message=f"{ref} is not a decision of {slug}")
        if d.status in ("DECIDED", "SUPERSEDED"):
            raise ValidationException(
                message=f"{ref} is {d.status} — ADRs are superseded, never edited: write a new decision with supersedes: [{ref}]"
            )
        if not (verdict or "").strip() or not (rationale or "").strip():
            raise ValidationException(message="verdict and rationale: both required")
        fields = {
            "verdict": verdict.strip(),
            "rationale": rationale.strip(),
            "decided_by": actor.principal,
            "decided_on": utcnow().date().isoformat(),
            "provisional": "no",
        }
        return self._write(slug, [WriteOp(ref=ref, fields=fields, note="ruled in the inbox")], actor)

    def approve(self, slug: str, target: str, role: str, at_sha: Optional[str], note: Optional[str], actor: Actor) -> WriteResult:
        require_human(actor)
        fields = {"target": [target], "role": role}
        if at_sha:
            fields["at_sha"] = at_sha
        if note:
            fields["note"] = note
        return self._write(slug, [WriteOp(type="approval", title=f"{role} approves {target}", fields=fields)], actor)

    def sign_ac(self, slug: str, ref: str, at_sha: str, actor: Actor) -> WriteResult:
        require_human(actor)
        g = self.records.graph(self.records.initiative(slug))
        ac = g.get(ref)
        if ac is None or ac.type != "acceptance_criterion":
            raise ValidationException(message=f"{ref} is not an acceptance criterion of {slug}")
        if g.f(ac, "manual") != "yes":
            raise ValidationException(message=f"{ref} is not a manual AC — automated ACs are proven by test runs")
        if "qa" not in g.roles_of(actor.principal):
            raise ValidationException(message=f"{actor.principal} is not the qa of {slug}")
        return self._write(
            slug, [WriteOp(ref=ref, fields={"signed_by": actor.principal, "signed_at_sha": at_sha or ""}, note="signed by QA")], actor
        )

    def retire_ac(self, slug: str, ref: str, because: str, actor: Actor) -> WriteResult:
        require_human(actor)
        if not (because or "").strip():
            raise ValidationException(message="because: required — why this criterion no longer applies")
        return self._write(slug, [WriteOp(ref=ref, fields={"retired_because": because.strip()}, note="retired")], actor)

    def promote_learning(self, ref: str, actor: Actor) -> WriteResult:
        require_human(actor)
        return self._write(GLOBAL_SLUG, [WriteOp(ref=ref, fields={"stage": "promoted"}, note="promoted")], actor)
