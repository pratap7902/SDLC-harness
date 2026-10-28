"""Test database. Default: a fresh in-memory SQLite per test (StaticPool — one connection
shared with the TestClient's thread). TEST_DATABASE_URL=mysql+mysqlconnector://… runs the
same tests on MySQL (`make test-mysql`): one engine per session, tables wiped per test."""

import os

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.base.models.mysql_base import Base
from app.core.database import make_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def mysql_engine():
    if not TEST_DATABASE_URL:
        yield None
        return
    engine = make_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(mysql_engine):
    if mysql_engine is not None:
        with mysql_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
        yield mysql_engine
        return
    engine = make_engine("sqlite+pysqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()
