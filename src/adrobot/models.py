from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from adrobot.db import Base


class Campaign(Base):
    """Local identity of a campaign already present in Keitaro."""

    __tablename__ = "campaigns"
    __table_args__ = (CheckConstraint("keitaro_id > 0", name="positive_keitaro_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
