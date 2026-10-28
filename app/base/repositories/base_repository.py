from typing import Generic, List, Optional, Type, TypeVar

from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    def get_by_id(self, id: int) -> Optional[ModelType]:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self) -> List[ModelType]:
        return self.db.query(self.model).all()

    def create(self, obj_in: dict) -> ModelType:
        obj_db = self.model(**obj_in)
        self.db.add(obj_db)
        self.db.commit()
        self.db.refresh(obj_db)
        return obj_db
