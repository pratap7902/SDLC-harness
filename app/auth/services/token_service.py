"""Bearer tokens (actor_tokens): mint, look up, revoke. The plaintext is shown once, at
mint time; only its sha256 is stored."""

import hashlib
import secrets
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.auth.models.actor_token import ActorToken
from app.auth.repositories.actor_token_repository import ActorTokenRepository
from app.core.utils.actor import CALLER_KINDS, Actor
from app.core.utils.time import utcnow
from app.exceptions import NotFoundException, ValidationException

TOKEN_PREFIX = "srs_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ActorTokenRepository(db)

    def mint(
        self, principal: str, kind: str, roles: Iterable[str] = (), label: str = "", expires_at: Optional[datetime] = None
    ) -> Tuple[str, ActorToken]:
        principal = (principal or "").strip()
        if not principal:
            raise ValidationException(message="principal: required (the person or runner the token speaks for)")
        if kind not in CALLER_KINDS:
            raise ValidationException(message=f"kind: one of {' | '.join(CALLER_KINDS)} — `system` is the service itself")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        row = self.repo.add(
            ActorToken(
                token_hash=hash_token(token),
                prefix=token[:12],
                principal=principal[:128],
                kind=kind,
                roles=sorted({r.strip() for r in roles if r and r.strip()}),
                label=(label or "")[:200],
                created_at=utcnow(),
                expires_at=expires_at,
            )
        )
        self.db.commit()
        return token, row

    def lookup(self, token: str) -> Optional[ActorToken]:
        """The live token row, or None (unknown, revoked, expired)."""
        if not token:
            return None
        row = self.repo.by_hash(hash_token(token))
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= utcnow():
            return None
        if row.kind not in CALLER_KINDS:
            return None  # never honour a row claiming `system`
        return row

    def actor(self, token: str) -> Optional[Actor]:
        row = self.lookup(token)
        if row is None:
            return None
        return Actor(principal=row.principal, kind=row.kind, roles=tuple(row.roles or ()), via="api")

    def revoke(self, token_id: int) -> ActorToken:
        row = self.repo.get(token_id)
        if row is None:
            raise NotFoundException(message=f"No token {token_id}")
        row.revoked_at = row.revoked_at or utcnow()
        self.db.commit()
        return row

    def list(self) -> List[ActorToken]:
        return self.repo.all()
