from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kopdes.infrastructure.db.base import Base


class EventLogModel(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("connection_profiles.id"),
        nullable=True,
        index=True,
    )
    level: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    profile: Mapped["ConnectionProfileModel"] = relationship(back_populates="events")
