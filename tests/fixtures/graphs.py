"""Small in-memory graphs for table-driven status / gate tests (no database)."""

from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional

from app.blueprint.services.blueprint_loader import get_blueprint
from app.initiatives.models.record import Record
from app.initiatives.models.record_link import RecordLink
from app.initiatives.services.record_graph import RecordGraph

T0 = datetime(2026, 10, 29, 12, 0, 0)


def rec(ref: str, type_: Optional[str] = None, **fields) -> Record:
    bp = get_blueprint()
    type_ = type_ or bp.type_of_ref(ref)
    return Record(
        initiative_id=1, type=type_, ref=ref, title=ref, status="", fields=fields, meta={}, head_rev=1,
        created_by="t", updated_by="t", created_at=T0, updated_at=T0,
    )


def graph(records: List[Record], leases=(), review_items=(), snapshot_hash="h") -> RecordGraph:
    """Typed links come from the records' refs fields, as the write path would make them."""
    bp = get_blueprint()
    links = []
    for r in records:
        for f in bp.types[r.type].refs_fields():
            for to in (r.fields or {}).get(f.name) or []:
                links.append(RecordLink(initiative_id=1, from_ref=r.ref, to_ref=to, kind=f.link_kind))
    initiative = SimpleNamespace(id=1, slug="t", title="T", snapshot_hash=snapshot_hash)
    return RecordGraph(bp, initiative, records, links, leases=leases, review_items=review_items)


def people(**roles) -> List[Record]:
    return [rec(f"A-{i + 1}", person=p, role=role, scope=["initiative"]) for i, (role, p) in enumerate(roles.items())]
