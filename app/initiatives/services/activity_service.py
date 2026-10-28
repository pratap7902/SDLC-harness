"""The activity feed: every revision and every review-item resolution of an initiative,
newest first — the same join the drift report is built on, unfiltered."""

from typing import Annotated, List, Optional

from fastapi import Depends

from app.core.utils.time import iso
from app.initiatives.repositories.event_repository import EventRepository
from app.initiatives.services.record_service import RecordService


class ActivityService:
    def __init__(self, records: Annotated[RecordService, Depends()]):
        self.records = records

    def feed(self, slug: str, since: Optional[str] = None, ref: Optional[str] = None, actor: Optional[str] = None, limit: int = 200) -> List[dict]:
        i = self.records.initiative(slug)
        types = {r.ref: r.type for r in self.records.records.list_for(i.id)}
        out = []
        for rev in self.records.revisions.list_for_initiative(i.id):
            out.append(
                {
                    "kind": "revision",
                    "at": iso(rev.created_at),
                    "ref": rev.ref,
                    "type": types.get(rev.ref),
                    "rev": rev.rev,
                    "action": "created" if rev.rev == 1 else "updated",
                    "title": rev.title,
                    "status": rev.status,
                    "actor": rev.actor,
                    "actor_kind": rev.actor_kind,
                    "note": rev.note,
                    "because": rev.cause_refs or [],
                    "batch_id": rev.batch_id,
                }
            )
        for item in self.records.reviews.all_for(i.id):
            out.append(
                {
                    "kind": "review_item",
                    "at": iso(item.created_at),
                    "ref": item.target_ref,
                    "type": types.get(item.target_ref),
                    "action": "queued",
                    "title": f"{item.target_ref} up for review ← {item.cause_ref}: {item.what_moved}",
                    "status": "open",
                    "actor": item.created_by,
                    "actor_kind": None,
                    "note": "",
                    "because": [item.cause_ref],
                    "review_item_id": item.id,
                }
            )
            if item.resolved_at:
                out.append(
                    {
                        "kind": "review_item",
                        "at": iso(item.resolved_at),
                        "ref": item.target_ref,
                        "type": types.get(item.target_ref),
                        "action": item.status,
                        "title": f"{item.target_ref} {item.status} ({item.cause_ref})",
                        "status": item.status,
                        "actor": item.resolved_by,
                        "actor_kind": None,
                        "note": item.note or "",
                        "because": [item.cause_ref],
                        "review_item_id": item.id,
                    }
                )
        if since:
            out = [x for x in out if (x["at"] or "") >= since]
        if ref:
            out = [x for x in out if x["ref"] == ref]
        if actor:
            out = [x for x in out if (x["actor"] or "").startswith(actor)]
        out.sort(key=lambda x: (x["at"] or "", x.get("rev") or 0), reverse=True)
        return out[:limit]

    def events(self, slug: Optional[str], since: int = 0, limit: int = 200) -> List[dict]:
        initiative_id = self.records.initiative(slug).id if slug else None
        return [
            {
                "id": e.id,
                "ts": iso(e.ts),
                "kind": e.kind,
                "subject": e.subject,
                "actor": e.actor,
                "batch_id": e.batch_id,
                "payload": e.payload or {},
            }
            for e in EventRepository(self.records.db).since(initiative_id, since, limit)
        ]
