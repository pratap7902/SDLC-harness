"""The single application database: SQLite (default, var/dev.db) or MySQL."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.database import db_settings


def make_engine(url: str, **kwargs) -> Engine:
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
        engine = create_engine(url, **kwargs)
        sqlite_transactions(engine)
        return engine
    return create_engine(url, pool_pre_ping=True, **kwargs)


def sqlite_transactions(engine: Engine) -> None:
    """pysqlite's own transaction handling breaks SAVEPOINTs; let SQLAlchemy emit BEGIN."""

    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")


engine_primary = make_engine(db_settings.url())
SessionLocalPrimary = sessionmaker(autocommit=False, autoflush=False, bind=engine_primary)


def get_primary_db() -> Session:
    """Yield a session for the primary database."""
    db = SessionLocalPrimary()
    try:
        yield db
    finally:
        db.close()
