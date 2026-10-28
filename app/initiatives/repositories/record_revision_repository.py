from typing import List

from sqlalchemy.orm import Session

from app.base.repositories.base_repository import BaseRepository
from app.initiatives.models.record import Record
from app.initiatives.models.record_revision import RecordRevision


class RecordRevisionRepository(BaseRepository[RecordRevision]):
    def __init__(self, db: Session):
        super().__init__(model=RecordRevision, db=db)

    def snapshot(
        self, record: Record, links: list, actor: str, actor_kind: str, batch_id: str, note: str, cause_refs: list
    ) -> RecordRevision:
        """Append the record's current state. Flushes, never commits."""
        rev = RecordRevision(
            record_id=record.id,
            initiative_id=record.initiative_id,
            ref=record.ref,
            rev=record.head_rev,
            title=record.title,
            status=record.status or "",
            fields=dict(record.fields or {}),
            links=list(links),
            actor=actor,
            actor_kind=actor_kind,
            batch_id=batch_id,
            note=(note or "")[:300],
            cause_refs=sorted(set(cause_refs or [])),
        )
        self.db.add(rev)
        self.db.flush()
        return rev

    def list_for_record(self, record_id: int) -> List[RecordRevision]:
        return (
            self.db.query(RecordRevision)
            .filter(RecordRevision.record_id == record_id)
            .order_by(RecordRevision.rev.desc())
            .all()
        )

    def list_for_initiative(self, initiative_id: int) -> List[RecordRevision]:
        return (
            self.db.query(RecordRevision)
            .filter(RecordRevision.initiative_id == initiative_id)
            .order_by(RecordRevision.id.asc())
            .all()
        )
