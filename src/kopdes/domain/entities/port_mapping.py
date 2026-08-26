from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PortMapping:
    id: str
    name: str
    description: str
    ssh_host: str
    ssh_port: int = 22
    ssh_username: str = ""
    local_host: str = "127.0.0.1"
    local_port: int = 5433
    remote_host: str = "127.0.0.1"
    remote_port: int = 5432
    identity_file: str | None = None
    encrypted_password: str | None = None
    auto_reconnect: bool = True
    enabled: bool = True
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
