from typing import List, Optional

from sqlalchemy.orm import Session

from app.initiatives.models.event import Event


class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, kind: str, initiative_id: int, subject: str, actor: str, batch_id: str = "", payload: Optional[dict] = None) -> Event:
        event = Event(
            kind=kind,
            initiative_id=initiative_id,
            subject=subject[:128],
            actor=actor[:128],
            batch_id=batch_id,
            payload=payload or {},
        )
        self.db.add(event)
        return event

    def since(self, initiative_id: Optional[int], since: int = 0, limit: int = 200) -> List[Event]:
        q = self.db.query(Event).filter(Event.id > since)
        if initiative_id is not None:
            q = q.filter(Event.initiative_id == initiative_id)
        return q.order_by(Event.id.asc()).limit(limit).all()
