from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kopdes.infrastructure.db.base import Base


class ConnectionProfileModel(Base):
    __tablename__ = "connection_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    protocol: Mapped[str] = mapped_column(String(64), index=True)
    server_address: Mapped[str] = mapped_column(String(255), index=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_metric: Mapped[int] = mapped_column(Integer, default=100)
    dns_servers: Mapped[str] = mapped_column(Text, default="")
    mtu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keepalive: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    config_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    tags: Mapped[list["TagModel"]] = relationship(
        secondary="profile_tags",
        back_populates="profiles",
    )
    sessions: Mapped[list["ConnectionSessionModel"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["EventLogModel"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
