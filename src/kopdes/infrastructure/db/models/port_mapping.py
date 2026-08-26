from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kopdes.infrastructure.db.base import Base


class PortMappingModel(Base):
    __tablename__ = "port_mappings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ssh_host: Mapped[str] = mapped_column(String(255), index=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_username: Mapped[str] = mapped_column(String(255), default="")
    local_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    local_port: Mapped[int] = mapped_column(Integer, index=True)
    remote_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    remote_port: Mapped[int] = mapped_column(Integer)
    identity_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
