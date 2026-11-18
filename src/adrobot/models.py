from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
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
