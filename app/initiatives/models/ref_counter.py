from sqlalchemy import BigInteger, Column, Integer, String

from app.base.models.mysql_base import MySQLBaseModel


class RefCounter(MySQLBaseModel):
    """Next number per (scope, prefix). Read FOR UPDATE inside the batch's transaction."""

    __tablename__ = "ref_counters"

    initiative_id = Column(BigInteger, primary_key=True, autoincrement=False)
    prefix = Column(String(8), primary_key=True)
    next_n = Column(Integer, nullable=False, default=1)
