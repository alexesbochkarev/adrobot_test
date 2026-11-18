"""add stream editor snapshots and drafts

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.CheckConstraint("keitaro_id > 0", name=op.f("ck_offers_positive_keitaro_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offers")),
        sa.UniqueConstraint("keitaro_id", name=op.f("uq_offers_keitaro_id")),
    )
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("schema_kind", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "schema_kind IN ('landings', 'redirect', 'action')",
            name=op.f("ck_streams_valid_schema"),
        ),
        sa.CheckConstraint("keitaro_id > 0", name=op.f("ck_streams_positive_keitaro_id")),
        sa.CheckConstraint("position > 0", name=op.f("ck_streams_positive_position")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_streams_positive_revision")),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_streams_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_streams")),
        sa.UniqueConstraint("keitaro_id", name=op.f("uq_streams_keitaro_id")),
    )
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_streams_campaign_id"), ["campaign_id"], unique=False)

    op.create_table(
        "stream_offers",
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column("published_share", sa.Integer(), nullable=True),
        sa.Column("published_pinned", sa.Boolean(), nullable=False),
        sa.Column("published_removed", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "NOT published_removed OR (published_share = 0 AND NOT published_pinned)",
            name=op.f("ck_stream_offers_published_removed_has_no_share"),
        ),
        sa.CheckConstraint(
            "NOT removed OR (share = 0 AND NOT pinned)",
            name=op.f("ck_stream_offers_removed_has_no_share"),
        ),
        sa.CheckConstraint(
            "published_share IS NOT NULL OR (NOT published_removed AND NOT published_pinned)",
            name=op.f("ck_stream_offers_new_link_has_no_snapshot"),
        ),
        sa.CheckConstraint(
            "published_share IS NULL OR published_share BETWEEN 0 AND 100",
            name=op.f("ck_stream_offers_published_share_range"),
        ),
        sa.CheckConstraint("share BETWEEN 0 AND 100", name=op.f("ck_stream_offers_share_range")),
        sa.ForeignKeyConstraint(
            ["offer_id"], ["offers.id"], name=op.f("fk_stream_offers_offer_id_offers")
        ),
        sa.ForeignKeyConstraint(
            ["stream_id"],
            ["streams.id"],
            name=op.f("fk_stream_offers_stream_id_streams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stream_id", "offer_id", name=op.f("pk_stream_offers")),
    )


def downgrade() -> None:
    op.drop_table("stream_offers")
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_streams_campaign_id"))

    op.drop_table("streams")
    op.drop_table("offers")
