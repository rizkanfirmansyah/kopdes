from __future__ import annotations

from time import monotonic
from threading import Lock

import psutil

from kopdes.application.dtos.runtime_state import InterfaceSnapshot


class InterfaceMonitor:
    CACHE_WINDOW_SECONDS = 0.25

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_snapshot: list[InterfaceSnapshot] = []
        self._last_snapshot_at = 0.0
        self._last_prefixes: tuple[str, ...] | None = None
        self._last_counters = psutil.net_io_counters(pernic=True)
        self._last_ts = monotonic()

    def collect(self, prefixes: tuple[str, ...] = ("tun", "tap", "ppp")) -> list[InterfaceSnapshot]:
        normalized_prefixes = tuple(prefixes)
        with self._lock:
            now = monotonic()
            if (
                self._last_snapshot
                and self._last_prefixes == normalized_prefixes
                and now - self._last_snapshot_at < self.CACHE_WINDOW_SECONDS
            ):
                return list(self._last_snapshot)
            snapshots = self._collect(normalized_prefixes)
            self._last_snapshot = list(snapshots)
            self._last_snapshot_at = monotonic()
            self._last_prefixes = normalized_prefixes
            return snapshots

    def _collect(self, prefixes: tuple[str, ...]) -> list[InterfaceSnapshot]:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        counters = psutil.net_io_counters(pernic=True)
        now = monotonic()
        elapsed = max(now - self._last_ts, 1e-6)
        snapshots: list[InterfaceSnapshot] = []

        for name, stat in stats.items():
            if not name.startswith(prefixes):
                continue
            counter = counters.get(name)
            previous = self._last_counters.get(name)
            rx_rate = 0.0
            tx_rate = 0.0
            if counter and previous:
                rx_rate = max(counter.bytes_recv - previous.bytes_recv, 0) / elapsed
                tx_rate = max(counter.bytes_sent - previous.bytes_sent, 0) / elapsed
            ipv4 = None
            for addr in addrs.get(name, []):
                if getattr(addr, "family", None) == 2:
                    ipv4 = addr.address
                    break
            snapshots.append(
                InterfaceSnapshot(
                    name=name,
                    kind=self._classify(name),
                    is_up=stat.isup,
                    mtu=stat.mtu,
                    ipv4=ipv4,
                    rx_bytes=counter.bytes_recv if counter else 0,
                    tx_bytes=counter.bytes_sent if counter else 0,
                    rx_rate_bps=rx_rate,
                    tx_rate_bps=tx_rate,
                    err_in=counter.errin if counter else 0,
                    err_out=counter.errout if counter else 0,
                )
            )

        self._last_counters = counters
        self._last_ts = now
        return sorted(snapshots, key=lambda item: item.name)

    def _classify(self, name: str) -> str:
        if name.startswith("tun"):
            return "tun"
        if name.startswith("tap"):
            return "tap"
        return "ppp"
