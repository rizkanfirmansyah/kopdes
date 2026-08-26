from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kopdes.shared.enums import ProtocolType


@dataclass(slots=True)
class ConnectionProfile:
    id: str
    name: str
    description: str
    server_address: str
    protocol: ProtocolType
    port: int | None = None
    username: str | None = None
    encrypted_password: str | None = None
    route_metric: int = 100
    dns_servers: list[str] = field(default_factory=list)
    mtu: int | None = None
    keepalive: int | None = None
    auto_reconnect: bool = True
    allow_multiple: bool = False
    tags: list[str] = field(default_factory=list)
    config_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
