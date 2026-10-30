from sqlalchemy import JSON, BigInteger, Column, Integer, String, UniqueConstraint

from app.base.models.mysql_base import BigId, MySQLBaseModel, Timestamp
from app.core.utils.time import utcnow


class Delivery(MySQLBaseModel):
    """One notification to one person on one channel. `dedupe_key` (e.g.
    `gap_routed:3:G-2:arjun`) makes sending idempotent; failures retry with backoff until
    TEAMS_NOTIFY_MAX_ATTEMPTS, then the row is `dead`."""

    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("dedupe_key", "channel", name="uq_deliveries_key_channel"),)

    id = Column(BigId, primary_key=True, autoincrement=True)
    dedupe_key = Column(String(200), nullable=False)
    channel = Column(String(16), nullable=False)  # teams
    person = Column(String(80), nullable=False)
    kind = Column(String(32), nullable=False)  # gap_routed | review_item_queued | approval_stale | overdue
    initiative_id = Column(BigInteger, nullable=False, default=0)
    subject = Column(String(64), nullable=False, default="")
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="pending")  # pending | sent | failed | dead
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(400), nullable=True)
    conversation_id = Column(String(200), nullable=True)
    activity_id = Column(String(200), nullable=True)
    created_at = Column(Timestamp, default=utcnow, nullable=False)
    sent_at = Column(Timestamp, nullable=True)
    next_attempt_at = Column(Timestamp, nullable=True)
