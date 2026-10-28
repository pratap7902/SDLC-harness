from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.base.models.mysql_base import BigId, MySQLBaseModel
from app.core.utils.time import utcnow


class Record(MySQLBaseModel):
    """One typed object of an initiative (initiative_id 0 = global scope: standards,
    learnings). `type` and `fields` are governed by blueprint/objects.yaml, not columns.
    `status` is a cache of the derived status — the graph re-derives it on every load."""

    __tablename__ = "records"
    __table_args__ = (
        UniqueConstraint("initiative_id", "ref", name="uq_records_initiative_ref"),
        Index("ix_records_initiative_type", "initiative_id", "type"),
    )

    id = Column(BigId, primary_key=True, autoincrement=True)
    initiative_id = Column(BigInteger, nullable=False, default=0)
    type = Column(String(40), nullable=False)
    ref = Column(String(64), nullable=False)
    title = Column(String(300), nullable=False)
    status = Column(String(40), nullable=False, default="")
    fields = Column(JSON, nullable=False, default=dict)
    # Service-owned bookkeeping: per-field stamps (who/when), narrative fingerprints.
    meta = Column(JSON, nullable=False, default=dict)
    stage = Column(String(16), nullable=False, default="")
    head_rev = Column(Integer, nullable=False, default=1)
    created_by = Column(String(128), nullable=False, default="")
    updated_by = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)
