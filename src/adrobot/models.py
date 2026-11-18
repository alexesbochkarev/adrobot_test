from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adrobot.db import Base


class Campaign(Base):
    """Local identity of a campaign already present in Keitaro."""

    __tablename__ = "campaigns"
    __table_args__ = (CheckConstraint("keitaro_id > 0", name="positive_keitaro_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    editor_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    sync_token: Mapped[str | None] = mapped_column(String(36))


class CampaignCreation(Base):
    """Durable creation intent; UUID also acts as the idempotency key."""

    __tablename__ = "campaign_creations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'unknown')", name="valid_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    phase: Mapped[str] = mapped_column(String(40), default="validation")
    remote_campaign_id: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (CheckConstraint("keitaro_id > 0", name="positive_keitaro_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))


class Stream(Base):
    __tablename__ = "streams"
    __table_args__ = (
        CheckConstraint("keitaro_id > 0", name="positive_keitaro_id"),
        CheckConstraint("revision > 0", name="positive_revision"),
        CheckConstraint("position > 0", name="positive_position"),
        CheckConstraint("schema_kind IN ('landings', 'redirect', 'action')", name="valid_schema"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    schema_kind: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    remote_present: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    remote_snapshot: Mapped[dict | None] = mapped_column(JSON)
    campaign: Mapped[Campaign] = relationship()
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.offer_id"
    )

    # Every editor operation bumps the parent revision, including link-only changes.
    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}

    @property
    def is_dirty(self) -> bool:
        return any(
            row.published_share is None
            or (row.share, row.pinned, row.removed)
            != (row.published_share, row.published_pinned, row.published_removed)
            for row in self.offers
        )


class StreamOffer(Base):
    """Current draft and last confirmed local snapshot of a stream/offer association."""

    __tablename__ = "stream_offers"
    __table_args__ = (
        CheckConstraint("share BETWEEN 0 AND 100", name="share_range"),
        CheckConstraint(
            "published_share IS NULL OR published_share BETWEEN 0 AND 100",
            name="published_share_range",
        ),
        CheckConstraint("NOT removed OR (share = 0 AND NOT pinned)", name="removed_has_no_share"),
        CheckConstraint(
            "NOT published_removed OR (published_share = 0 AND NOT published_pinned)",
            name="published_removed_has_no_share",
        ),
        CheckConstraint(
            "published_share IS NOT NULL OR (NOT published_removed AND NOT published_pinned)",
            name="new_link_has_no_snapshot",
        ),
    )

    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), primary_key=True
    )
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), primary_key=True)
    share: Mapped[int] = mapped_column(Integer)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL means this association was added in the draft and has never been published.
    published_share: Mapped[int | None] = mapped_column(Integer)
    published_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    published_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    stream: Mapped[Stream] = relationship(back_populates="offers")
    offer: Mapped[Offer] = relationship()


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'conflict', 'unknown')",
            name="valid_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    expected_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    phase: Mapped[str] = mapped_column(String(32), default="checking")
    before_snapshot: Mapped[dict] = mapped_column(JSON)
    desired_offers: Mapped[list] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
