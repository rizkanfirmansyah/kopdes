from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from kopdes.infrastructure.db.base import Base


class HealthCheckModel(Base):
    __tablename__ = "health_checks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("connection_profiles.id"),
        index=True,
    )
    check_type: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=10)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=3)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)
    recovery_threshold: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
