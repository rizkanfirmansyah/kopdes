from __future__ import annotations

from dataclasses import dataclass, field

from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.shared.enums import ConnectionStatus


@dataclass(slots=True)
class ActionResult:
    success: bool
    message: str
    details: str | None = None
    data: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class OpenVpnConfig:
    name: str
    config_path: str
    backend: str
    imported_at: str | None = None


@dataclass(slots=True)
class OpenVpnSession:
    name: str
    session_path: str
    status_text: str
    backend: str
    config_path: str | None = None
    pid: int | None = None
    interface_name: str | None = None


@dataclass(slots=True)
class InterfaceSnapshot:
    name: str
    kind: str
    is_up: bool
    mtu: int
    ipv4: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_rate_bps: float = 0.0
    tx_rate_bps: float = 0.0
    err_in: int = 0
    err_out: int = 0


@dataclass(slots=True)
class RouteEntry:
    destination: str
    gateway: str | None
    device: str | None
    table: str
    metric: int | None
    source: str | None = None
    protocol: str | None = None
    scope: str | None = None


@dataclass(slots=True)
class RuleEntry:
    priority: int | None
    table: str | None
    source: str | None
    destination: str | None
    action: str | None


@dataclass(slots=True)
class DnsStatus:
    servers: list[str] = field(default_factory=list)
    search_domains: list[str] = field(default_factory=list)
    resolver_source: str = "/etc/resolv.conf"


@dataclass(slots=True)
class ConnectionRow:
    profile_id: str
    status: ConnectionStatus
    name: str
    protocol: str
    server: str
    backend: str = "-"
    local_ip: str = "-"
    remote_ip: str = "-"
    latency_ms: float | None = None
    rx_rate_bps: float = 0.0
    tx_rate_bps: float = 0.0
    total_rx_bytes: int = 0
    total_tx_bytes: int = 0
    duration_text: str = "-"
    reconnect_count: int = 0
    last_error: str = "-"
    interface_name: str = "-"
    gateway: str = "-"
    packet_loss: str = "-"
    upload_history: list[float] = field(default_factory=list)
    download_history: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ConnectionInspector:
    profile: ConnectionProfile
    row: ConnectionRow
    dns: DnsStatus
    routes: list[RouteEntry] = field(default_factory=list)
    rules: list[RuleEntry] = field(default_factory=list)
    interfaces: list[InterfaceSnapshot] = field(default_factory=list)
    tunnel_ip: str = "-"
    gateway: str = "-"
    dns_display: str = "-"
    packet_loss: str = "-"
    mtu: str = "-"
    reconnect_count: int = 0
    log_messages: list[str] = field(default_factory=list)
    upload_history: list[float] = field(default_factory=list)
    download_history: list[float] = field(default_factory=list)
