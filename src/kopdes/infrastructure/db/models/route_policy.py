from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from kopdes.infrastructure.db.base import Base


class RoutePolicyModel(Base):
    __tablename__ = "route_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("connection_profiles.id"),
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(64))
    table_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric: Mapped[int] = mapped_column(Integer, default=100)
    source_cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=1000)
    is_failover: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
