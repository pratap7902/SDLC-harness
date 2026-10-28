from typing import Optional

from sqlalchemy.orm import Session

from app.initiatives.models.write_batch import WriteBatch


class WriteBatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, batch_id: str) -> Optional[WriteBatch]:
        return self.db.get(WriteBatch, batch_id)

    def add(self, batch: WriteBatch) -> None:
        self.db.add(batch)
        self.db.flush()
