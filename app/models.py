"""Aggregates every ORM model so `Base.metadata` is fully populated (Alembic env.py and
the test fixture's create_all import this)."""

from app.initiatives.models import (  # noqa: F401
    Event,
    Initiative,
    Lease,
    Record,
    RecordLink,
    RecordRevision,
    RefCounter,
    ReviewItem,
    WriteBatch,
)

__all__ = [
    "Event",
    "Initiative",
    "Lease",
    "Record",
    "RecordLink",
    "RecordRevision",
    "RefCounter",
    "ReviewItem",
    "WriteBatch",
]
