from sqlalchemy import JSON, Column, DateTime, String

from app.base.models.mysql_base import BigId, MySQLBaseModel
from app.core.utils.time import utcnow


class Initiative(MySQLBaseModel):
    """The scope container (one feature). `spec_snapshot` pins the requirement the work
    started from: {requirement, work_item_url, created_by, at}; its hash is mirrored on the
    `initiative` singleton record so a re-pin is a material change."""

    __tablename__ = "initiatives"

    id = Column(BigId, primary_key=True, autoincrement=True)
    slug = Column(String(64), nullable=False, unique=True)
    title = Column(String(300), nullable=False)
    work_item_url = Column(String(512), nullable=True)
    spec_snapshot = Column(JSON, nullable=False, default=dict)
    snapshot_hash = Column(String(64), nullable=False, default="")
    created_by = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    closed_at = Column(DateTime, nullable=True)
