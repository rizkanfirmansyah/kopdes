from __future__ import annotations

import socket
from dataclasses import dataclass
from time import perf_counter

from kopdes.infrastructure.system.command_runner import CommandRunner
from kopdes.shared.enums import HealthCheckType


@dataclass(slots=True)
class HealthCheckResult:
    ok: bool
    latency_ms: float | None
    detail: str


class HealthMonitor:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def run(self, check_type: HealthCheckType, target: str, timeout: int = 3) -> HealthCheckResult:
        if check_type == HealthCheckType.PING:
            started = perf_counter()
            result = self._command_runner.run(["ping", "-c", "1", "-W", str(timeout), target], timeout=timeout + 2)
            latency = (perf_counter() - started) * 1000
            return HealthCheckResult(
                ok=result.return_code == 0,
                latency_ms=round(latency, 2),
                detail=result.stdout.strip() or result.stderr.strip(),
            )
        if check_type == HealthCheckType.TCP:
            started = perf_counter()
            host, port = target.split(":", maxsplit=1)
            try:
                with socket.create_connection((host, int(port)), timeout=timeout):
                    latency = (perf_counter() - started) * 1000
                    return HealthCheckResult(True, round(latency, 2), "TCP port reachable")
            except OSError as exc:
                return HealthCheckResult(False, None, str(exc))
        return HealthCheckResult(False, None, f"Unsupported check type: {check_type.value}")
