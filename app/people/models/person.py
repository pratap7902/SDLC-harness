from sqlalchemy import JSON, BigInteger, Boolean, Column, Index, String, UniqueConstraint

from app.base.models.mysql_base import BigId, MySQLBaseModel, Timestamp
from app.core.utils.time import utcnow


class Person(MySQLBaseModel):
    """A canonical human: one row however many platforms they appear on. `handle` is what
    assignments, approvals and answers name (`priya`); roles stay assignments."""

    __tablename__ = "people"

    id = Column(BigId, primary_key=True, autoincrement=True)
    handle = Column(String(80), nullable=False, unique=True)
    name = Column(String(200), nullable=False, default="")
    email = Column(String(254), nullable=True, unique=True)  # lower-cased; the merge key
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(Timestamp, default=utcnow, nullable=False)
    updated_at = Column(Timestamp, default=utcnow, nullable=False)


class PersonIdentity(MySQLBaseModel):
    """A person's account on one source: `teams` (Entra object id), `cloudflare` (the
    Access email), `azure_devops` (uniqueName)."""

    __tablename__ = "person_identities"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_person_identities_source_ext"),)

    id = Column(BigId, primary_key=True, autoincrement=True)
    person_id = Column(BigInteger, nullable=False, index=True)
    source = Column(String(32), nullable=False)
    external_id = Column(String(200), nullable=False)
    email = Column(String(254), nullable=True)
    display_name = Column(String(200), nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)
    # per-source state, e.g. teams: {"conversation_id": "a:1…"} (the bot's 1:1 chat)
    meta = Column(JSON, nullable=False, default=dict)
    synced_at = Column(Timestamp, default=utcnow, nullable=False)


class PeopleReviewItem(MySQLBaseModel):
    """A directory entry the sync could not merge on its own — `unmatched` (no person has
    that email) or `conflict` (the email or the account points at more than one person).
    An admin links it, creates a person from it, or ignores it; never an automatic
    duplicate."""

    __tablename__ = "people_review"
    __table_args__ = (Index("ix_people_review_open", "status", "source", "external_id"),)

    id = Column(BigId, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)
    external_id = Column(String(200), nullable=False)
    email = Column(String(254), nullable=True)
    display_name = Column(String(200), nullable=False, default="")
    reason = Column(String(16), nullable=False)  # unmatched | conflict
    detail = Column(String(400), nullable=False, default="")
    candidates = Column(JSON, nullable=False, default=list)  # handles involved
    status = Column(String(16), nullable=False, default="open")  # open | linked | created | ignored
    created_at = Column(Timestamp, default=utcnow, nullable=False)
    resolved_by = Column(String(128), nullable=True)
    resolved_at = Column(Timestamp, nullable=True)
