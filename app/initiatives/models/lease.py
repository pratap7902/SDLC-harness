from sqlalchemy import Column, DateTime, String

from app.base.models.mysql_base import MySQLBaseModel
from app.core.utils.time import utcnow


class Lease(MySQLBaseModel):
    """A claim on a work item (`task:T-3`, `draft:order-events`, `gap:order-events:G-4`).
    Expired leases are free again — expiry is evaluated on read, never by a sweeper."""

    __tablename__ = "leases"

    item_key = Column(String(128), primary_key=True)
    holder = Column(String(128), nullable=False)
    acquired_at = Column(DateTime, default=utcnow, nullable=False)
    heartbeat_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
