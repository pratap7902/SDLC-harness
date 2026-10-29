"""actor_tokens: bearer tokens → actor, kind, roles (AUTH_MODE=token)

Revision ID: 0002_actor_tokens
Revises: 0001_initial
Create Date: 2026-10-29
"""

import sqlalchemy as sa
import sqlalchemy.dialects.mysql  # noqa: F401
from alembic import op

revision = "0002_actor_tokens"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

BigId = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
Ts = sa.DateTime().with_variant(sa.dialects.mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.create_table(
        "actor_tokens",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("principal", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("created_at", Ts, nullable=False),
        sa.Column("expires_at", Ts, nullable=True),
        sa.Column("revoked_at", Ts, nullable=True),
        sa.Column("last_used_at", Ts, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("actor_tokens")
