from sqlalchemy import JSON, BigInteger, Column, DateTime, Index, String

from app.base.models.mysql_base import BigId, MySQLBaseModel
from app.core.utils.time import utcnow


class Event(MySQLBaseModel):
    """Append-only event log: record_written, baseline_created, review_item_queued,
    gate_changed, initiative_created, lease_claimed … Read with ?since=<id>."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_subject", "subject", "id"),
        Index("ix_events_initiative", "initiative_id", "id"),
    )

    id = Column(BigId, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=utcnow, nullable=False)
    kind = Column(String(40), nullable=False)
    initiative_id = Column(BigInteger, nullable=False, default=0)
    subject = Column(String(128), nullable=False, default="")
    actor = Column(String(128), nullable=False, default="")
    batch_id = Column(String(64), nullable=False, default="")
    payload = Column(JSON, nullable=False, default=dict)
