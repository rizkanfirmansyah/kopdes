from __future__ import annotations

from pathlib import Path

from kopdes.application.dtos.runtime_state import DnsStatus


class DnsMonitor:
    def __init__(self, resolv_conf: Path = Path("/etc/resolv.conf")) -> None:
        self._resolv_conf = resolv_conf

    def collect(self) -> DnsStatus:
        if not self._resolv_conf.exists():
            return DnsStatus()
        servers: list[str] = []
        search_domains: list[str] = []
        for line in self._resolv_conf.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("nameserver "):
                servers.append(stripped.split(maxsplit=1)[1])
            if stripped.startswith("search "):
                search_domains.extend(stripped.split()[1:])
        return DnsStatus(
            servers=servers,
            search_domains=search_domains,
            resolver_source=str(self._resolv_conf),
        )
