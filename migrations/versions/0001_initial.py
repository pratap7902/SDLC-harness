"""initial: the generic record store

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-29

Hand-written, portable (SQLite + MySQL). Record types, fields, vocabularies, gates and
catalogs are YAML (blueprint/) — migrations are for these generic tables only.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

BigId = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "initiatives",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("work_item_url", sa.String(512), nullable=True),
        sa.Column("spec_snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "records",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("head_rev", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("initiative_id", "ref", name="uq_records_initiative_ref"),
    )
    op.create_index("ix_records_initiative_type", "records", ["initiative_id", "type"])
    op.create_table(
        "record_revisions",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.BigInteger(), sa.ForeignKey("records.id"), nullable=False),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        sa.Column("cause_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("record_id", "rev", name="uq_record_revisions_rev"),
    )
    op.create_index("ix_record_revisions_record_id", "record_revisions", ["record_id"])
    op.create_index("ix_record_revisions_initiative_id", "record_revisions", ["initiative_id"])
    op.create_table(
        "record_links",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("from_ref", sa.String(64), nullable=False),
        sa.Column("to_ref", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("initiative_id", "from_ref", "to_ref", "kind", name="uq_record_links"),
    )
    op.create_index("ix_record_links_to", "record_links", ["initiative_id", "to_ref"])
    op.create_table(
        "review_items",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("cause_ref", sa.String(64), nullable=False),
        sa.Column("cause_rev", sa.Integer(), nullable=False),
        sa.Column("what_moved", sa.String(255), nullable=False),
        sa.Column("target_ref", sa.String(64), nullable=False),
        sa.Column("path", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("route_to", sa.String(80), nullable=True),
        sa.Column("domain", sa.String(16), nullable=True),
        sa.Column("judged_by", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_review_items_open", "review_items", ["initiative_id", "status", "target_ref"])
    op.create_index("ix_review_items_cause", "review_items", ["initiative_id", "cause_ref"])
    op.create_table(
        "write_batches",
        sa.Column("batch_id", sa.String(64), primary_key=True),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("ops_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "leases",
        sa.Column("item_key", sa.String(128), primary_key=True),
        sa.Column("holder", sa.String(128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ref_counters",
        sa.Column("initiative_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("prefix", sa.String(8), primary_key=True),
        sa.Column("next_n", sa.Integer(), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", BigId, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("initiative_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_events_subject", "events", ["subject", "id"])
    op.create_index("ix_events_initiative", "events", ["initiative_id", "id"])


def downgrade() -> None:
    for table in (
        "events",
        "ref_counters",
        "leases",
        "write_batches",
        "review_items",
        "record_links",
        "record_revisions",
        "records",
        "initiatives",
    ):
        op.drop_table(table)
