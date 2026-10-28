from typing import List, Optional

from sqlalchemy.orm import Session

from app.base.repositories.base_repository import BaseRepository
from app.initiatives.models.initiative import Initiative


class InitiativeRepository(BaseRepository[Initiative]):
    def __init__(self, db: Session):
        super().__init__(model=Initiative, db=db)

    def get_by_slug(self, slug: str) -> Optional[Initiative]:
        return self.db.query(Initiative).filter(Initiative.slug == slug).first()

    def list_ordered(self) -> List[Initiative]:
        return self.db.query(Initiative).order_by(Initiative.created_at.desc(), Initiative.id.desc()).all()

    def add(self, initiative: Initiative) -> Initiative:
        self.db.add(initiative)
        self.db.flush()
        return initiative
