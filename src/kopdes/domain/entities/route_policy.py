from __future__ import annotations

from dataclasses import dataclass

from kopdes.shared.enums import RouteMode


@dataclass(slots=True)
class RoutePolicy:
    id: str
    profile_id: str
    mode: RouteMode
    table_name: str | None = None
    metric: int = 100
    source_cidr: str | None = None
    destination_cidr: str | None = None
    gateway: str | None = None
    priority: int = 1000
    is_failover: bool = False
