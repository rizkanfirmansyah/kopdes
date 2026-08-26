from __future__ import annotations

import logging
from pathlib import Path

from kopdes.application.dtos.runtime_state import DnsStatus


LOGGER = logging.getLogger(__name__)


class DnsMonitor:
    def __init__(self, resolv_conf: Path = Path("/etc/resolv.conf")) -> None:
        self._resolv_conf = resolv_conf

    def collect(self) -> DnsStatus:
        try:
            if not self._resolv_conf.exists():
                return DnsStatus()
            raw = self._resolv_conf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            LOGGER.exception("Could not read resolver configuration")
            return DnsStatus(resolver_source=str(self._resolv_conf))
        servers: list[str] = []
        search_domains: list[str] = []
        for line in raw.splitlines():
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
