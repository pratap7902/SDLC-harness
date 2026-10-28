from sqlalchemy import orm

Base = orm.declarative_base()


class MySQLBaseModel(Base):
    """
    Base model for all MySQL entities
    """

    __abstract__ = True

    def to_dict(self):
        """Convert model to dictionary"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    @classmethod
    def from_dict(cls, data: dict):
        """Create model from dictionary"""
        return cls(**data)


# Primary keys: BIGINT on MySQL, INTEGER on SQLite (only `INTEGER PRIMARY KEY`
# autoincrements there).
from sqlalchemy import BigInteger, Integer  # noqa: E402

BigId = BigInteger().with_variant(Integer, "sqlite")
