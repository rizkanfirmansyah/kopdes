from __future__ import annotations

from dataclasses import dataclass, field

from kopdes.shared.enums import ProtocolType


@dataclass(slots=True)
class ConnectionProfileInput:
    name: str
    description: str
    server_address: str
    protocol: ProtocolType
    port: int | None = None
    username: str | None = None
    password: str | None = None
    route_metric: int = 100
    dns_servers: list[str] = field(default_factory=list)
    mtu: int | None = None
    keepalive: int | None = None
    auto_reconnect: bool = True
    allow_multiple: bool = False
    tags: list[str] = field(default_factory=list)
    config_payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class DashboardStats:
    total_connections: int
    active_connections: int
    failed_connections: int
    bandwidth_usage_mbps: float
    system_load: float
    memory_usage_percent: float


@dataclass(slots=True)
class PortMappingInput:
    name: str
    description: str
    ssh_host: str
    ssh_username: str
    local_port: int
    remote_host: str
    remote_port: int
    ssh_port: int = 22
    local_host: str = "127.0.0.1"
    identity_file: str | None = None
    password: str | None = None
    auto_reconnect: bool = True
    enabled: bool = True
