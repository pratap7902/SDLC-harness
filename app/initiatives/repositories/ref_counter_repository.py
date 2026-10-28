from sqlalchemy.orm import Session

from app.initiatives.models.ref_counter import RefCounter
from app.initiatives.repositories.record_repository import RecordRepository


class RefCounterRepository:
    """Mints refs: SELECT … FOR UPDATE on (scope, prefix), bump next_n — inside the batch's
    transaction, so a rolled-back batch gives its numbers back. Seeded from the highest
    existing ref the first time a prefix is used."""

    def __init__(self, db: Session):
        self.db = db

    def next(self, initiative_id: int, prefix: str) -> int:
        row = (
            self.db.query(RefCounter)
            .filter(RefCounter.initiative_id == initiative_id, RefCounter.prefix == prefix)
            .with_for_update()
            .first()
        )
        if row is None:
            start = RecordRepository(self.db).max_number(initiative_id, prefix) + 1
            row = RefCounter(initiative_id=initiative_id, prefix=prefix, next_n=start)
            self.db.add(row)
            self.db.flush()
        n = row.next_n
        row.next_n = n + 1
        self.db.flush()
        return n
