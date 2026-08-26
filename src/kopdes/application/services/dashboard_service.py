from __future__ import annotations

from kopdes.application.dtos.connection_profile_dto import DashboardStats
from kopdes.application.ports.repositories import (
    ConnectionProfileRepository,
    ConnectionSessionRepository,
)
from kopdes.infrastructure.system.system_metrics import SystemMetricsCollector
from kopdes.shared.enums import ConnectionStatus


class DashboardService:
    def __init__(
        self,
        profile_repository: ConnectionProfileRepository,
        session_repository: ConnectionSessionRepository,
        metrics_collector: SystemMetricsCollector,
    ) -> None:
        self._profile_repository = profile_repository
        self._session_repository = session_repository
        self._metrics_collector = metrics_collector

    def get_stats(self) -> DashboardStats:
        profiles = self._profile_repository.list_all()
        sessions = self._session_repository.list_latest()
        active = sum(1 for item in sessions if item.status == ConnectionStatus.ACTIVE)
        failed = sum(1 for item in sessions if item.status == ConnectionStatus.FAILED)
        metrics = self._metrics_collector.collect()
        return DashboardStats(
            total_connections=len(profiles),
            active_connections=active,
            failed_connections=failed,
            bandwidth_usage_mbps=metrics.bandwidth_usage_mbps,
            system_load=metrics.system_load,
            memory_usage_percent=metrics.memory_usage_percent,
        )
