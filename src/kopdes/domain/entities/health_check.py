from __future__ import annotations

from dataclasses import dataclass

from kopdes.shared.enums import HealthCheckType


@dataclass(slots=True)
class HealthCheck:
    id: str
    profile_id: str
    check_type: HealthCheckType
    target: str
    interval_seconds: int = 10
    timeout_seconds: int = 3
    failure_threshold: int = 3
    recovery_threshold: int = 1
    enabled: bool = True
