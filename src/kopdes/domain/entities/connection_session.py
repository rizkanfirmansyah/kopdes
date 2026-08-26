from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kopdes.shared.enums import ConnectionStatus


@dataclass(slots=True)
class ConnectionSession:
    id: str
    profile_id: str
    status: ConnectionStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    latency_ms: float | None = None
    packet_loss: float | None = None
    jitter_ms: float | None = None
    bytes_in: int = 0
    bytes_out: int = 0
    reconnect_count: int = 0
    last_error: str | None = None
    local_ip: str | None = None
    remote_ip: str | None = None
