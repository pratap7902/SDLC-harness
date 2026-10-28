from typing import List, Optional

from sqlalchemy.orm import Session

from app.base.repositories.base_repository import BaseRepository
from app.core.utils.time import utcnow
from app.initiatives.models.review_item import ReviewItem


class ReviewItemRepository(BaseRepository[ReviewItem]):
    def __init__(self, db: Session):
        super().__init__(model=ReviewItem, db=db)

    def open_for(self, initiative_id: int) -> List[ReviewItem]:
        return (
            self.db.query(ReviewItem)
            .filter(ReviewItem.initiative_id == initiative_id, ReviewItem.status == "open")
            .order_by(ReviewItem.id.asc())
            .all()
        )

    def all_for(self, initiative_id: int, status: Optional[str] = None) -> List[ReviewItem]:
        q = self.db.query(ReviewItem).filter(ReviewItem.initiative_id == initiative_id)
        if status:
            q = q.filter(ReviewItem.status == status)
        return q.order_by(ReviewItem.id.desc()).all()

    def open_everywhere(self) -> List[ReviewItem]:
        return self.db.query(ReviewItem).filter(ReviewItem.status == "open").order_by(ReviewItem.id.asc()).all()

    def open_pair(self, initiative_id: int, target_ref: str, cause_ref: str) -> Optional[ReviewItem]:
        return (
            self.db.query(ReviewItem)
            .filter(
                ReviewItem.initiative_id == initiative_id,
                ReviewItem.target_ref == target_ref,
                ReviewItem.cause_ref == cause_ref,
                ReviewItem.status == "open",
            )
            .first()
        )

    def resolve_target(self, initiative_id: int, target_ref: str, status: str, note: str, by: str) -> List[ReviewItem]:
        items = (
            self.db.query(ReviewItem)
            .filter(
                ReviewItem.initiative_id == initiative_id,
                ReviewItem.target_ref == target_ref,
                ReviewItem.status == "open",
            )
            .all()
        )
        now = utcnow()
        for item in items:
            item.status, item.note, item.resolved_by, item.resolved_at = status, note, by, now
        return items
