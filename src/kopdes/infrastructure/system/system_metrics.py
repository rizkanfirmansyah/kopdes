from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic

import psutil


@dataclass(slots=True)
class SystemMetrics:
    bandwidth_usage_mbps: float
    system_load: float
    memory_usage_percent: float


class SystemMetricsCollector:
    def __init__(self) -> None:
        self._last_io = psutil.net_io_counters()
        self._last_sample_at = monotonic()
        self._lock = Lock()

    def collect(self) -> SystemMetrics:
        with self._lock:
            try:
                load_avg = psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0.0
                memory = psutil.virtual_memory().percent
                current_io = psutil.net_io_counters()
                now = monotonic()
                elapsed = max(now - self._last_sample_at, 0.001)
                delta_bytes = max(current_io.bytes_recv - self._last_io.bytes_recv, 0) + max(
                    current_io.bytes_sent - self._last_io.bytes_sent,
                    0,
                )
                self._last_io = current_io
                self._last_sample_at = now
                bandwidth_mbps = round((delta_bytes * 8) / 1_000_000 / elapsed, 2)
                return SystemMetrics(
                    bandwidth_usage_mbps=max(bandwidth_mbps, 0.0),
                    system_load=round(load_avg, 2),
                    memory_usage_percent=round(memory, 2),
                )
            except (OSError, RuntimeError, ValueError):
                return SystemMetrics(0.0, 0.0, 0.0)
