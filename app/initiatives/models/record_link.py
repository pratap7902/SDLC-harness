from sqlalchemy import BigInteger, Column, Index, String, UniqueConstraint

from app.base.models.mysql_base import BigId, MySQLBaseModel, Timestamp
from app.core.utils.time import utcnow


class RecordLink(MySQLBaseModel):
    """A directed, typed edge between two refs. Endpoints are refs, not ids, so an edge may
    point at a global record (STD-14). `kind` is the field's link_kind (`supersedes`,
    `covers`, `because`, …), `mentions` for a bare ref in text, `relates` for op.link."""

    __tablename__ = "record_links"
    __table_args__ = (
        UniqueConstraint("initiative_id", "from_ref", "to_ref", "kind", name="uq_record_links"),
        Index("ix_record_links_to", "initiative_id", "to_ref"),
    )

    id = Column(BigId, primary_key=True, autoincrement=True)
    initiative_id = Column(BigInteger, nullable=False, default=0)
    from_ref = Column(String(64), nullable=False)
    to_ref = Column(String(300), nullable=False)
    kind = Column(String(20), nullable=False)
    created_by = Column(String(128), nullable=False, default="")
    created_at = Column(Timestamp, default=utcnow, nullable=False)
