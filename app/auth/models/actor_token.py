from sqlalchemy import JSON, Column, String

from app.base.models.mysql_base import BigId, MySQLBaseModel, Timestamp
from app.core.utils.time import utcnow


class ActorToken(MySQLBaseModel):
    """A bearer token → who (principal), as what (kind: human | agent) and with which
    service roles (admin, ci, …). Only the sha256 of the token is stored; `prefix` is its
    first characters, to tell tokens apart in listings. Minted by scripts/mint_token.py."""

    __tablename__ = "actor_tokens"

    id = Column(BigId, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    prefix = Column(String(12), nullable=False)
    principal = Column(String(128), nullable=False)
    kind = Column(String(16), nullable=False)
    roles = Column(JSON, nullable=False, default=list)
    label = Column(String(200), nullable=False, default="")
    created_at = Column(Timestamp, default=utcnow, nullable=False)
    expires_at = Column(Timestamp, nullable=True)
    revoked_at = Column(Timestamp, nullable=True)
    last_used_at = Column(Timestamp, nullable=True)
