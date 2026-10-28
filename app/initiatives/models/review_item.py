from sqlalchemy import BigInteger, Column, Index, Integer, String, Text

from app.base.models.mysql_base import BigId, MySQLBaseModel, Timestamp
from app.core.utils.time import utcnow


class ReviewItem(MySQLBaseModel):
    """"`cause` changed — does `target` still stand?" One open row per (target, cause),
    enforced in the repository. Closed by a decision, never by time: `revised` (the target
    was edited), `upheld` (someone said why it still holds), `dismissed`."""

    __tablename__ = "review_items"
    __table_args__ = (
        Index("ix_review_items_open", "initiative_id", "status", "target_ref"),
        Index("ix_review_items_cause", "initiative_id", "cause_ref"),
    )

    id = Column(BigId, primary_key=True, autoincrement=True)
    initiative_id = Column(BigInteger, nullable=False)
    cause_ref = Column(String(64), nullable=False)
    cause_rev = Column(Integer, nullable=False, default=0)
    what_moved = Column(String(255), nullable=False, default="")
    target_ref = Column(String(64), nullable=False)
    path = Column(String(16), nullable=False, default="link")  # link | mention | scope
    status = Column(String(16), nullable=False, default="open")  # open|upheld|revised|dismissed
    route_to = Column(String(80), nullable=True)
    domain = Column(String(16), nullable=True)
    judged_by = Column(String(20), nullable=False, default="rules")
    note = Column(Text, nullable=True)
    created_by = Column(String(128), nullable=False, default="")
    created_at = Column(Timestamp, default=utcnow, nullable=False)
    resolved_by = Column(String(128), nullable=True)
    resolved_at = Column(Timestamp, nullable=True)
