from typing import List

from sqlalchemy.orm import Session

from app.base.repositories.base_repository import BaseRepository
from app.initiatives.models.record_link import RecordLink


class RecordLinkRepository(BaseRepository[RecordLink]):
    """Directed, typed edges between refs. Flushes, never commits."""

    def __init__(self, db: Session):
        super().__init__(model=RecordLink, db=db)

    def list_for(self, initiative_id: int) -> List[RecordLink]:
        return self.db.query(RecordLink).filter(RecordLink.initiative_id == initiative_id).all()

    def out_of(self, initiative_id: int, from_ref: str) -> List[RecordLink]:
        return (
            self.db.query(RecordLink)
            .filter(RecordLink.initiative_id == initiative_id, RecordLink.from_ref == from_ref)
            .all()
        )

    def ensure(self, initiative_id: int, from_ref: str, to_ref: str, kind: str, actor: str = "") -> bool:
        exists = (
            self.db.query(RecordLink.id)
            .filter(
                RecordLink.initiative_id == initiative_id,
                RecordLink.from_ref == from_ref,
                RecordLink.to_ref == to_ref,
                RecordLink.kind == kind,
            )
            .first()
        )
        if exists:
            return False
        self.db.add(RecordLink(initiative_id=initiative_id, from_ref=from_ref, to_ref=to_ref, kind=kind, created_by=actor))
        self.db.flush()
        return True

    def remove(self, initiative_id: int, from_ref: str, to_ref: str, kind: str) -> bool:
        deleted = (
            self.db.query(RecordLink)
            .filter(
                RecordLink.initiative_id == initiative_id,
                RecordLink.from_ref == from_ref,
                RecordLink.to_ref == to_ref,
                RecordLink.kind == kind,
            )
            .delete()
        )
        return bool(deleted)
