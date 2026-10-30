from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.people.models.person import PeopleReviewItem, Person, PersonIdentity


def norm_email(email: Optional[str]) -> Optional[str]:
    email = (email or "").strip().lower()
    return email or None


class PeopleRepository:
    def __init__(self, db: Session):
        self.db = db

    # people
    def all(self) -> List[Person]:
        return self.db.query(Person).order_by(Person.handle).all()

    def get(self, person_id: int) -> Optional[Person]:
        return self.db.get(Person, person_id)

    def by_handle(self, handle: str) -> Optional[Person]:
        return self.db.query(Person).filter(Person.handle == handle).one_or_none()

    def by_email(self, email: Optional[str]) -> Optional[Person]:
        email = norm_email(email)
        if not email:
            return None
        return self.db.query(Person).filter(func.lower(Person.email) == email).one_or_none()

    def add(self, person: Person) -> Person:
        self.db.add(person)
        self.db.flush()
        return person

    # identities
    def identities(self, person_id: Optional[int] = None) -> List[PersonIdentity]:
        q = self.db.query(PersonIdentity)
        if person_id is not None:
            q = q.filter(PersonIdentity.person_id == person_id)
        return q.order_by(PersonIdentity.id).all()

    def identity(self, source: str, external_id: str) -> Optional[PersonIdentity]:
        return (
            self.db.query(PersonIdentity)
            .filter(PersonIdentity.source == source, PersonIdentity.external_id == external_id)
            .one_or_none()
        )

    def identity_of(self, person_id: int, source: str) -> Optional[PersonIdentity]:
        return (
            self.db.query(PersonIdentity)
            .filter(PersonIdentity.person_id == person_id, PersonIdentity.source == source)
            .first()
        )

    def add_identity(self, identity: PersonIdentity) -> PersonIdentity:
        self.db.add(identity)
        self.db.flush()
        return identity

    # review list
    def review(self, status: Optional[str] = "open") -> List[PeopleReviewItem]:
        q = self.db.query(PeopleReviewItem)
        if status:
            q = q.filter(PeopleReviewItem.status == status)
        return q.order_by(PeopleReviewItem.id).all()

    def review_item(self, item_id: int) -> Optional[PeopleReviewItem]:
        return self.db.get(PeopleReviewItem, item_id)

    def open_review_for(self, source: str, external_id: str) -> Optional[PeopleReviewItem]:
        return (
            self.db.query(PeopleReviewItem)
            .filter(
                PeopleReviewItem.source == source,
                PeopleReviewItem.external_id == external_id,
                PeopleReviewItem.status == "open",
            )
            .first()
        )

    def add_review(self, item: PeopleReviewItem) -> PeopleReviewItem:
        self.db.add(item)
        self.db.flush()
        return item
