"""Stable JSON shapes shared by REST and the UI (snake_case keys). One place builds each
shape, so an endpoint never invents its own variant of a record."""

from typing import List, Optional

from app.core.utils.time import iso
from app.initiatives.models.initiative import Initiative
from app.initiatives.models.record import Record
from app.initiatives.models.record_revision import RecordRevision
from app.initiatives.models.review_item import ReviewItem
from app.initiatives.services.record_graph import RecordGraph


def record_json(r: Record, g: RecordGraph, detail: bool = False) -> dict:
    bp = g.bp
    spec = bp.types[r.type]
    fields = bp.ordered_fields(r.type, r.fields or {})
    out = {
        "ref": r.ref,
        "type": r.type,
        "title": r.title,
        "status": r.status,
        "pill": bp.pill(r.status),
        "line": (fields.get(spec.line) if spec.line else None),
        "rev": r.head_rev,
        "fields": fields,
        "created_by": r.created_by,
        "created_at": iso(r.created_at),
        "updated_by": r.updated_by,
        "updated_at": iso(r.updated_at),
    }
    if detail:
        out["links"] = {"out": g.edges_out(r.ref), "in": g.edges_in(r.ref)}
        out["stamps"] = (r.meta or {}).get("stamps", {})
        out["stale"] = g.stale_slots(r)
        out["review_items"] = [review_item_json(i) for i in g.open_review_items if i.target_ref == r.ref]
    return out


def revision_json(rev: RecordRevision) -> dict:
    return {
        "rev": rev.rev,
        "ref": rev.ref,
        "title": rev.title,
        "status": rev.status,
        "fields": rev.fields or {},
        "links": rev.links or [],
        "actor": rev.actor,
        "actor_kind": rev.actor_kind,
        "batch_id": rev.batch_id,
        "note": rev.note,
        "because": rev.cause_refs or [],
        "at": iso(rev.created_at),
    }


def review_item_json(i: ReviewItem) -> dict:
    return {
        "id": i.id,
        "target": i.target_ref,
        "cause": i.cause_ref,
        "cause_rev": i.cause_rev,
        "what_moved": i.what_moved,
        "path": i.path,
        "status": i.status,
        "route_to": i.route_to,
        "domain": i.domain,
        "judged_by": i.judged_by,
        "note": i.note,
        "created_by": i.created_by,
        "created_at": iso(i.created_at),
        "resolved_by": i.resolved_by,
        "resolved_at": iso(i.resolved_at),
    }


def initiative_json(i: Initiative, g: Optional[RecordGraph] = None) -> dict:
    out = {
        "id": i.id,
        "slug": i.slug,
        "title": i.title,
        "work_item_url": i.work_item_url,
        "created_by": i.created_by,
        "created_at": iso(i.created_at),
        "closed_at": iso(i.closed_at),
        "snapshot_hash": i.snapshot_hash,
    }
    if g is not None:
        singleton = g.get("initiative")
        out["phase"] = singleton.status if singleton is not None else "UNASSIGNED"
        out["pill"] = g.bp.pill(out["phase"])
        out["summary"] = g.f("initiative", "summary", "")
    return out


def gate_json(result) -> dict:
    return result.to_dict()


def records_json(records: List[Record], g: RecordGraph) -> List[dict]:
    return [record_json(r, g) for r in records]
