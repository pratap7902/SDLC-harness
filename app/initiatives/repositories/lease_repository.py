from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.initiatives.models.lease import Lease


class LeaseRepository:
    """Atomic claims that are correct on SQLite and MySQL alike: insert, or a conditional
    UPDATE … WHERE expired OR mine, judged by rowcount (no SELECT … FOR UPDATE needed)."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str) -> Optional[Lease]:
        return self.db.get(Lease, key)

    def active(self, now: datetime) -> List[Lease]:
        return self.db.query(Lease).filter(Lease.expires_at > now).all()

    def try_claim(self, key: str, holder: str, now: datetime, expires: datetime) -> bool:
        result = self.db.execute(
            update(Lease)
            .where(Lease.item_key == key, or_(Lease.expires_at <= now, Lease.holder == holder))
            .values(holder=holder, acquired_at=now, heartbeat_at=now, expires_at=expires)
        )
        if result.rowcount:
            return True
        if self.db.get(Lease, key) is not None:
            return False
        try:
            with self.db.begin_nested():
                self.db.add(Lease(item_key=key, holder=holder, acquired_at=now, heartbeat_at=now, expires_at=expires))
        except IntegrityError:
            return False
        return True

    def heartbeat(self, key: str, holder: str, now: datetime, expires: datetime) -> bool:
        result = self.db.execute(
            update(Lease)
            .where(Lease.item_key == key, Lease.holder == holder, Lease.expires_at > now)
            .values(heartbeat_at=now, expires_at=expires)
        )
        return bool(result.rowcount)

    def release(self, key: str, holder: str) -> bool:
        deleted = self.db.query(Lease).filter(Lease.item_key == key, Lease.holder == holder).delete()
        return bool(deleted)
