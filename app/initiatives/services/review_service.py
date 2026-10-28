"""The review queue. A MATERIAL change to a record (a field the blueprint marks
`material`, or arriving at one of its `material_statuses`) queues the records that rest on
it: linked to it either way (any link kind) or mentioning its ref, of the types its
`propagates_to` names. One hop: editing a queued record is itself a material change that
queues ITS dependents; `upheld` ("still holds, because …") stops the ripple.

Items close by a decision, never by time: `revised` (the target was edited, or became
SUPERSEDED / RETIRED / WITHDRAWN), `upheld`, `dismissed`."""

import re
from dataclasses import dataclass
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.blueprint.schemas.blueprint import Blueprint, RecordType
from app.core.utils.time import utcnow
from app.exceptions import NotFoundException, ValidationException
from app.initiatives.models.initiative import Initiative
from app.initiatives.models.record import Record
from app.initiatives.models.review_item import ReviewItem
from app.initiatives.repositories.review_item_repository import ReviewItemRepository
from app.initiatives.services.routing import Router
from config.settings import settings

DEAD = {"SUPERSEDED", "RETIRED", "WITHDRAWN", "REPLACED", "REJECTED"}
REF_IN_TEXT = re.compile(r"(?<![\w.-])([A-Z]{1,4}-\d+)(?![\w-])")
RESOLUTIONS = ("upheld", "revised", "dismissed")


def _clip(value, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def mentions_in(fields: dict) -> set:
    """Every ref a record's text names — bullets and row cells included."""
    parts: List[str] = []
    for value in (fields or {}).values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                parts += [str(c) for c in item.values()] if isinstance(item, dict) else [str(item)]
    return set(REF_IN_TEXT.findall(" ".join(parts)))


@dataclass
class Queued:
    target: str
    cause: str
    what_moved: str
    route_to: str

    def line(self) -> str:
        return f"{self.target} ← {self.cause}: {self.what_moved}" + (f" (→ {self.route_to})" if self.route_to else "")


class ReviewService:
    def __init__(self, db: Session, blueprint: Blueprint):
        self.db = db
        self.bp = blueprint
        self.repo = ReviewItemRepository(db)

    @staticmethod
    def material_change(spec: RecordType, before: dict, after: dict, status_before: str, status_after: str) -> str:
        """ "status OPEN → ANSWERED · verdict: “a” → “b”" — or "" when nothing material moved."""
        if not before:
            if status_after in spec.propagates_on_create:
                return f"created {status_after}: “{_clip(after.get(spec.line) or '')}”"
            return ""  # a new record invalidates nothing that already existed
        parts = []
        if status_before != status_after and spec.material_statuses and status_after in spec.material_statuses:
            parts.append(f"status {status_before} → {status_after}")
        for name, f in spec.fields.items():
            if not f.material:
                continue
            old, new = before.get(name), after.get(name)
            if old == new or not old:
                continue  # a first fill moves nothing that was relied on
            if isinstance(old, str) or isinstance(new, str):
                parts.append(f"{name}: “{_clip(old, 60)}” → “{_clip(new, 60)}”")
            else:
                parts.append(f"{name} changed")
        return " · ".join(parts)[:255]

    def candidates(self, graph, cause: Record) -> List[Tuple[Record, str]]:
        spec = self.bp.types[cause.type]
        allowed = set(spec.propagates_to)
        if not allowed:
            return []
        linked = graph.linked(cause.ref)
        named = mentions_in(cause.fields)
        out = []
        for record in graph.records:
            if record.ref == cause.ref or record.type not in allowed or record.status in DEAD:
                continue
            if cause.type == "initiative":
                out.append((record, "scope"))  # the singleton scopes everything in it
            elif record.ref in linked:
                out.append((record, "link"))
            elif cause.ref in mentions_in(record.fields) or record.ref in named:
                out.append((record, "mention"))
        return out

    def propagate(self, initiative: Initiative, graph, causes: List[Tuple[Record, str]], skip: set, actor: str) -> List[Queued]:
        """`skip` = refs written in the same batch: whoever changed the cause and its
        dependents together has, by that act, looked at them."""
        if not settings.review.REVIEW_PROPAGATION:
            return []
        router = Router(graph)
        queued: List[Queued] = []
        for cause, what_moved in causes:
            for target, path in self.candidates(graph, cause):
                if target.ref in skip:
                    continue
                route = router.route(target, cause)
                existing = self.repo.open_pair(initiative.id, target.ref, cause.ref)
                if existing:
                    existing.what_moved = f"{existing.what_moved} · then: {what_moved}"[:255]
                    existing.cause_rev = cause.head_rev
                else:
                    self.db.add(
                        ReviewItem(
                            initiative_id=initiative.id,
                            cause_ref=cause.ref,
                            cause_rev=cause.head_rev,
                            what_moved=what_moved[:255],
                            target_ref=target.ref,
                            path=path,
                            route_to=route.person,
                            domain=route.domain,
                            created_by=actor,
                        )
                    )
                queued.append(Queued(target.ref, cause.ref, what_moved, route.person or ""))
        self.db.flush()
        return queued

    def resolve_target(self, initiative: Initiative, target_ref: str, status: str, note: str, by: str) -> List[ReviewItem]:
        return self.repo.resolve_target(initiative.id, target_ref, status, note, by)

    def resolve(self, initiative: Initiative, item_id: int, resolution: str, note: str, by: str) -> ReviewItem:
        if resolution not in RESOLUTIONS:
            raise ValidationException(message=f"resolution: one of {' | '.join(RESOLUTIONS)}")
        if not (note or "").strip():
            raise ValidationException(message="note: required — say why it still holds / what you changed")
        item = self.repo.get_by_id(item_id)
        if item is None or item.initiative_id != initiative.id:
            raise NotFoundException(message=f"No review item {item_id} in {initiative.slug}")
        if item.status != "open":
            raise ValidationException(message=f"review item {item_id} is already {item.status}")
        item.status, item.note, item.resolved_by, item.resolved_at = resolution, note, by, utcnow()
        self.db.flush()
        return item
