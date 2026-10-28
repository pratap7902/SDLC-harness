"""Initiatives: start one (the intake), list them, read one's state, re-pin its
requirement, and the draft-review page (touchpoint 1).

The intake is `IntakeService.start(StartFeature, actor)`. The web UI's "start a feature"
form calls it through POST /api/initiatives; an Azure DevOps importer (deferred) builds the
same StartFeature from a work item and calls the same function — the work item URL rides
along as `work_item_url`, the work item's description becomes `requirement`."""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, List, Optional

from fastapi import Depends

from app.core.utils.actor import Actor
from app.core.utils.time import iso, utcnow
from app.exceptions import ConflictException, ValidationException
from app.initiatives.models.initiative import Initiative
from app.initiatives.schemas.write import WriteOp
from app.initiatives.services.gate_rules import GateRules, catalog_state
from app.initiatives.services.record_service import RecordService
from app.initiatives.services.review_service import (
    ReviewService,  # noqa: F401  (re-export for callers)
)
from app.initiatives.services.views import (
    initiative_json,
    record_json,
    review_item_json,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
ROLES = ("dri", "engg", "product", "design", "qa")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60].strip("-") or "initiative"


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


@dataclass
class StartFeature:
    """Everything a feature starts from. `requirement` is markdown (required); people are
    directory handles. An ADO importer fills the same shape."""

    title: str
    requirement: str
    dri: str
    engg: str
    slug: Optional[str] = None
    work_item_url: Optional[str] = None
    product: Optional[str] = None
    design: Optional[str] = None
    qa: Optional[str] = None
    prd_refs: Optional[List[str]] = None


class IntakeService:
    def __init__(self, records: RecordService):
        self.records = records
        self.db = records.db

    def start(self, req: StartFeature, actor: Actor) -> Initiative:
        errors = []
        if not (req.title or "").strip():
            errors.append("title: required")
        if not (req.requirement or "").strip():
            errors.append("requirement: required — the markdown the feature starts from")
        for role in ("dri", "engg"):
            if not (getattr(req, role) or "").strip():
                errors.append(f"{role}: required — a person's handle")
        slug = (req.slug or "").strip() or slugify(req.title)
        if not SLUG_RE.match(slug):
            errors.append("slug: 3–64 chars, lowercase letters, digits and dashes")
        if errors:
            raise ValidationException(message="; ".join(errors), error_data={"errors": errors})
        if self.records.initiatives.get_by_slug(slug) is not None:
            if req.slug:
                raise ConflictException(message=f"initiative '{slug}' already exists")
            base, n = slug, 2
            while self.records.initiatives.get_by_slug(f"{base}-{n}") is not None:
                n += 1
            slug = f"{base}-{n}"

        now = utcnow()
        snapshot = {
            "requirement": req.requirement,
            "work_item_url": req.work_item_url or None,
            "created_by": actor.name,
            "at": iso(now),
        }
        initiative = self.records.initiatives.add(
            Initiative(
                slug=slug,
                title=req.title.strip()[:300],
                work_item_url=req.work_item_url or None,
                spec_snapshot=snapshot,
                snapshot_hash=snapshot_hash(snapshot),
                created_by=actor.name,
                created_at=now,
            )
        )
        singleton = {"snapshot_hash": initiative.snapshot_hash}
        if req.work_item_url:
            singleton["work_item_url"] = req.work_item_url
        if req.prd_refs:
            singleton["prd_refs"] = list(req.prd_refs)
        ops = [WriteOp(type="initiative", title=initiative.title, fields=singleton, note="started")]
        for role in ROLES:
            person = (getattr(req, role) or "").strip()
            if person:
                ops.append(
                    WriteOp(
                        type="assignment",
                        title=f"{role}: {person}",
                        fields={"person": person, "role": role, "scope": ["initiative"]},
                    )
                )
        self.records.events.add("initiative_created", initiative.id, slug, actor.name, "", {"work_item_url": req.work_item_url})
        result = self.records.write(slug, ops, actor)
        if not result.ok:
            raise ValidationException(message="Could not start the feature", error_data=result.to_dict())
        return self.records.initiative(slug)


class InitiativeService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records
        self.bp = records.bp

    def start(self, req: StartFeature, actor: Actor) -> dict:
        initiative = IntakeService(self.records).start(req, actor)
        return self.state(initiative.slug)

    def list(self) -> List[dict]:
        out = []
        for i in self.records.initiatives.list_ordered():
            g = self.records.graph(i)
            drift = g.drift() if g.current_baseline() is not None else None
            out.append(
                {
                    **initiative_json(i, g),
                    "dri": g.person_for("dri"),
                    "engg": g.person_for("engg"),
                    "counts": {
                        "open_gaps": sum(1 for r in g.of_type("gap") if r.status == "OPEN"),
                        "open_decisions": sum(1 for r in g.of_type("decision") if r.status == "OPEN"),
                        "tasks": len(g.of_type("task")),
                        "tasks_done": sum(1 for t in g.of_type("task") if t.status == "DONE"),
                        "open_review_items": len(g.open_review_items),
                    },
                    "baseline": g.current_baseline().ref if g.current_baseline() is not None else None,
                    "drift": drift.summary() if drift is not None else None,
                }
            )
        return out

    def state(self, slug: str) -> dict:
        i = self.records.initiative(slug)
        g = self.records.graph(i)
        counts = {}
        for type_key in self.bp.types:
            c = Counter(r.status for r in g.of_type(type_key))
            if c:
                counts[type_key] = dict(c)
        baseline = g.current_baseline()
        drift = g.drift() if baseline is not None else None
        tasks = []
        for t in g.of_type("task"):
            gate = g.gate("GATE_PR", task=t.ref)
            task_drift = g.drift(task=t.ref) if baseline is not None else None
            tasks.append(
                {
                    **record_json(t, g),
                    "gate_pr": {"status": gate.status, "failing_rules": gate.failing_rules},
                    "drift": task_drift.summary() if task_drift is not None else None,
                }
            )
        lifecycle = self.bp.lifecycle
        return {
            "initiative": {**initiative_json(i, g), "spec_snapshot": i.spec_snapshot or {}},
            "phase": g.get("initiative").status if g.get("initiative") is not None else "UNASSIGNED",
            "assignments": [
                {"ref": a.ref, "person": g.f(a, "person"), "role": g.f(a, "role"), "scope": g.f(a, "scope") or [], "status": a.status}
                for a in g.of_type("assignment")
            ],
            "gates": [g.gate(key).to_dict() for key, gate in lifecycle.gates.items() if gate.scope == "initiative"],
            "tasks": tasks,
            "counts": counts,
            "open": {
                "decisions": [r.ref for r in g.of_type("decision") if r.status == "OPEN"],
                "gaps": [r.ref for r in g.of_type("gap") if r.status == "OPEN"],
                "review_items": len(g.open_review_items),
            },
            "stuck": [t.ref for t in g.of_type("task") if t.status == "STUCK"],
            "baseline": _baseline_json(baseline) if baseline is not None else None,
            "drift": drift.summary() if drift is not None else None,
            "stale": g.all_stale(),
            "catalog": {phase: catalog_state(g, phase) for phase in lifecycle.catalogs},
        }

    def repin(self, slug: str, requirement: str, work_item_url: Optional[str], actor: Actor) -> dict:
        """A human re-pins the requirement: a material change that queues the draft."""
        if not (requirement or "").strip():
            raise ValidationException(message="requirement: required")
        i = self.records.initiative(slug)
        snapshot = {
            "requirement": requirement,
            "work_item_url": work_item_url if work_item_url is not None else (i.spec_snapshot or {}).get("work_item_url"),
            "created_by": actor.name,
            "at": iso(utcnow()),
        }
        previous = dict(i.spec_snapshot or {})
        i.spec_snapshot = {**snapshot, "previous_hash": i.snapshot_hash, "previous_at": previous.get("at")}
        i.snapshot_hash = snapshot_hash(snapshot)
        if work_item_url is not None:
            i.work_item_url = work_item_url or None
        fields = {"snapshot_hash": i.snapshot_hash}
        if work_item_url is not None:
            fields["work_item_url"] = work_item_url or None
        result = self.records.write(slug, [WriteOp(ref="initiative", fields=fields, note="requirement re-pinned")], actor)
        if not result.ok:
            raise ValidationException(message="Re-pin rejected", error_data=result.to_dict())
        return {"state": self.state(slug), "write": result.to_dict()}

    def draft_page(self, slug: str) -> dict:
        """Touchpoint 1: the draft, its decisions with options, its ACs, its gaps, the
        draft-phase catalog, GATE_DRAFT and whether the DRI can approve now."""
        i = self.records.initiative(slug)
        g = self.records.graph(i)
        draft = g.get("draft")
        rules = GateRules(self.bp)
        blockers = rules.preconditions(g, "GATE_DRAFT")
        gate = g.gate("GATE_DRAFT")

        def decision_json(d):
            out = record_json(d, g, detail=True)
            out["superseded_by"] = g.in_(d.ref, "supersedes")
            out["sourced_acs"] = [a for a in g.in_(d.ref, "source") if g.bp.type_of_ref(a) == "acceptance_criterion"]
            return out

        spec_types = ("draft", "decision", "acceptance_criterion")
        return {
            "initiative": {**initiative_json(i, g), "spec_snapshot": i.spec_snapshot or {}},
            "draft": record_json(draft, g, detail=True) if draft is not None else None,
            "decisions": [decision_json(d) for d in g.of_type("decision")],
            "criteria": [record_json(a, g, detail=True) for a in g.of_type("acceptance_criterion")],
            "gaps": [record_json(x, g, detail=True) for x in g.of_type("gap")],
            "catalog": catalog_state(g, "draft"),
            "gate": gate.to_dict(),
            "can_approve": draft is not None and not blockers and gate.status != "PASSED",
            "approver": g.person_for("dri"),
            "approval_blockers": [
                {"rule": r.name, "failing": r.failing, "detail": r.detail} for r in blockers
            ]
            + ([{"rule": "draft_exists", "failing": [], "detail": "no draft yet"}] if draft is None else []),
            "approvals": [record_json(a, g) for a in g.of_type("approval") if "draft" in (g.f(a, "target") or [])],
            "baselines": [_baseline_json(b) for b in g.baselines()],
            "review_items": [
                review_item_json(r)
                for r in g.open_review_items
                if g.get(r.target_ref) is not None and g.get(r.target_ref).type in spec_types
            ],
        }


def _baseline_json(b) -> dict:
    f = b.fields or {}
    return {
        "ref": b.ref,
        "label": f.get("label"),
        "status": b.status,
        "approval": (f.get("approval") or [None])[0],
        "approved_by": f.get("approved_by"),
        "draft_rev": f.get("draft_rev"),
        "members": [m["ref"] for m in f.get("members") or []],
        "created_at": iso(b.created_at),
    }
