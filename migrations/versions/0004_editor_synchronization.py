"""add editor synchronization and publication journal

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("desired_offers", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'conflict', 'unknown')",
            name=op.f("ck_publications_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["stream_id"], ["streams.id"], name=op.f("fk_publications_stream_id_streams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
    )
    with op.batch_alter_table("publications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_publications_stream_id"), ["stream_id"], unique=False)

    # Native ADD avoids parent-table recreation and its cascading deletion of child rows.
    op.add_column(
        "campaigns", sa.Column("editor_revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("campaigns", sa.Column("sync_token", sa.String(length=36), nullable=True))
    op.add_column(
        "streams",
        sa.Column("remote_present", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("streams", sa.Column("remote_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_table("publications")
    # Native DROP COLUMN (SQLite >= 3.35) avoids rebuilding parents with CASCADE FKs enabled.
    op.drop_column("streams", "remote_snapshot")
    op.drop_column("streams", "remote_present")
    op.drop_column("campaigns", "sync_token")
    op.drop_column("campaigns", "editor_revision")
