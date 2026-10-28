from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.base.models.mysql_base import BigId, MySQLBaseModel
from app.core.utils.time import utcnow


class RecordRevision(MySQLBaseModel):
    """Append-only snapshot written on every change to a record. `cause_refs` is the
    `because` of this revision — what the drift report reads to explain a change."""

    __tablename__ = "record_revisions"
    __table_args__ = (UniqueConstraint("record_id", "rev", name="uq_record_revisions_rev"),)

    id = Column(BigId, primary_key=True, autoincrement=True)
    record_id = Column(BigInteger, ForeignKey("records.id"), nullable=False, index=True)
    initiative_id = Column(BigInteger, nullable=False, default=0, index=True)
    ref = Column(String(64), nullable=False, default="")
    rev = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    status = Column(String(40), nullable=False, default="")
    fields = Column(JSON, nullable=False, default=dict)
    links = Column(JSON, nullable=False, default=list)
    actor = Column(String(128), nullable=False, default="")
    actor_kind = Column(String(16), nullable=False, default="agent")
    batch_id = Column(String(64), nullable=False, default="")
    note = Column(String(300), nullable=False, default="")
    cause_refs = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utcnow, nullable=False)
