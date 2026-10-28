from typing import List, Optional

from sqlalchemy.orm import Session

from app.base.repositories.base_repository import BaseRepository
from app.initiatives.models.record import Record


class RecordRepository(BaseRepository[Record]):
    """Writes flush but never commit: a batch is one transaction, committed (or rolled
    back) by RecordService."""

    def __init__(self, db: Session):
        super().__init__(model=Record, db=db)

    def get_by_ref(self, initiative_id: int, ref: str) -> Optional[Record]:
        return self.db.query(Record).filter(Record.initiative_id == initiative_id, Record.ref == ref).first()

    def list_for(self, initiative_id: int, type_: Optional[str] = None) -> List[Record]:
        q = self.db.query(Record).filter(Record.initiative_id == initiative_id)
        if type_:
            q = q.filter(Record.type == type_)
        return q.order_by(Record.id.asc()).all()

    def max_number(self, initiative_id: int, prefix: str) -> int:
        refs = [
            r[0]
            for r in self.db.query(Record.ref)
            .filter(Record.initiative_id == initiative_id, Record.ref.like(f"{prefix}-%"))
            .all()
        ]
        nums = [int(ref.split("-", 1)[1]) for ref in refs if ref.split("-", 1)[1].isdigit()]
        return max(nums, default=0)

    def add(self, record: Record) -> Record:
        self.db.add(record)
        self.db.flush()
        return record
