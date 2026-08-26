from dataclasses import dataclass

from kopdes.application.services.dashboard_service import DashboardService
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.infrastructure.system.system_metrics import SystemMetrics
from kopdes.shared.enums import ConnectionStatus, ProtocolType


class FakeProfileRepository:
    def list_all(self):
        return [
            ConnectionProfile(
                id="1",
                name="vpn-a",
                description="",
                server_address="vpn-a.example",
                protocol=ProtocolType.OPENVPN,
            )
        ]


class FakeSessionRepository:
    def list_latest(self):
        return [
            ConnectionSession(id="s1", profile_id="1", status=ConnectionStatus.ACTIVE),
            ConnectionSession(id="s2", profile_id="2", status=ConnectionStatus.FAILED),
        ]


@dataclass
class FakeMetricsCollector:
    def collect(self):
        return SystemMetrics(
            bandwidth_usage_mbps=12.5,
            system_load=0.72,
            memory_usage_percent=48.3,
        )


def test_dashboard_service_aggregates_stats() -> None:
    service = DashboardService(
        FakeProfileRepository(),
        FakeSessionRepository(),
        FakeMetricsCollector(),
    )
    stats = service.get_stats()
    assert stats.total_connections == 1
    assert stats.active_connections == 1
    assert stats.failed_connections == 1
    assert stats.bandwidth_usage_mbps == 12.5
