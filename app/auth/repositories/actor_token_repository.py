from typing import List, Optional

from sqlalchemy.orm import Session

from app.auth.models.actor_token import ActorToken


class ActorTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def by_hash(self, token_hash: str) -> Optional[ActorToken]:
        return self.db.query(ActorToken).filter(ActorToken.token_hash == token_hash).one_or_none()

    def get(self, token_id: int) -> Optional[ActorToken]:
        return self.db.get(ActorToken, token_id)

    def all(self) -> List[ActorToken]:
        return self.db.query(ActorToken).order_by(ActorToken.id).all()

    def add(self, token: ActorToken) -> ActorToken:
        self.db.add(token)
        self.db.flush()
        return token
