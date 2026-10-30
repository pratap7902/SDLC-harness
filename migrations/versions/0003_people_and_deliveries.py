"""people directory (people, person_identities, people_review) and Teams deliveries

Revision ID: 0003_people_and_deliveries
Revises: 0002_actor_tokens
Create Date: 2026-10-30
"""

import sqlalchemy as sa
import sqlalchemy.dialects.mysql  # noqa: F401
from alembic import op

revision = "0003_people_and_deliveries"
down_revision = "0002_actor_tokens"
branch_labels = None
depends_on = None

BigId = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
Ts = sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("handle", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=True, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", Ts, nullable=False),
        sa.Column("updated_at", Ts, nullable=False),
    )
    op.create_table(
        "person_identities",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("synced_at", Ts, nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_person_identities_source_ext"),
    )
    op.create_index("ix_person_identities_person_id", "person_identities", ["person_id"])
    op.create_table(
        "people_review",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(400), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", Ts, nullable=False),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolved_at", Ts, nullable=True),
    )
    op.create_index("ix_people_review_open", "people_review", ["status", "source", "external_id"])
    op.create_table(
        "deliveries",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("person", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(400), nullable=True),
        sa.Column("conversation_id", sa.String(200), nullable=True),
        sa.Column("activity_id", sa.String(200), nullable=True),
        sa.Column("created_at", Ts, nullable=False),
        sa.Column("sent_at", Ts, nullable=True),
        sa.Column("next_attempt_at", Ts, nullable=True),
        sa.UniqueConstraint("dedupe_key", "channel", name="uq_deliveries_key_channel"),
    )


def downgrade() -> None:
    for table in ("deliveries", "people_review", "person_identities", "people"):
        op.drop_table(table)
