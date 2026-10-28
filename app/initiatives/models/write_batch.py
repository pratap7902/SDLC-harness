from sqlalchemy import JSON, BigInteger, Column, DateTime, String

from app.base.models.mysql_base import MySQLBaseModel
from app.core.utils.time import utcnow


class WriteBatch(MySQLBaseModel):
    """Idempotency: a batch_id seen before with the same ops returns the stored result."""

    __tablename__ = "write_batches"

    batch_id = Column(String(64), primary_key=True)
    initiative_id = Column(BigInteger, nullable=False, default=0)
    actor = Column(String(128), nullable=False, default="")
    actor_kind = Column(String(16), nullable=False, default="agent")
    ops_hash = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow, nullable=False)
