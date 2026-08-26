from datetime import datetime, timezone

from kopdes.application.dtos.runtime_state import DnsStatus, InterfaceSnapshot, OpenVpnSession, RouteEntry
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.infrastructure.system.session_monitor import SessionMonitor
from kopdes.shared.enums import ConnectionStatus, ProtocolType


class OpenVpnManagerStub:
    def __init__(self, sessions=None):
        self._sessions = sessions or []

    def list_sessions(self):
        return self._sessions


class PppManagerStub:
    def list_active_connections(self):
        return {}


class RouteManagerStub:
    def list_routes(self):
        return [RouteEntry(destination="default", gateway="10.8.0.1", device="tun0", table="main", metric=None)]

    def list_rules(self):
        return []


class InterfaceMonitorStub:
    def __init__(self, interfaces=None):
        self._interfaces = interfaces if interfaces is not None else [
            InterfaceSnapshot(
                name="tun0",
                kind="tun",
                is_up=True,
                mtu=1500,
                ipv4="10.8.0.148",
                rx_bytes=1024,
                tx_bytes=2048,
                rx_rate_bps=100.0,
                tx_rate_bps=200.0,
            )
        ]

    def collect(self):
        return self._interfaces


class DnsMonitorStub:
    def collect(self):
        return DnsStatus(servers=["8.8.8.8"])


class HealthMonitorStub:
    def run(self, check_type, target, timeout=2):
        raise AssertionError('health probe should not be called in build_rows test')


def test_session_monitor_marks_openvpn_active_when_named_session_and_tunnel_are_up() -> None:
    monitor = SessionMonitor(
        openvpn_manager=OpenVpnManagerStub(
            [OpenVpnSession(name="Majalaya", session_path="/tmp/majalaya.json", status_text="connected", backend="openvpn", interface_name="tun0")]
        ),
        ppp_manager=PppManagerStub(),
        route_manager=RouteManagerStub(),
        interface_monitor=InterfaceMonitorStub(),
        dns_monitor=DnsMonitorStub(),
        health_monitor=HealthMonitorStub(),
    )
    profile = ConnectionProfile(id="profile-1", name="Majalaya", description="test", server_address="103.175.217.180", protocol=ProtocolType.OPENVPN, config_payload={"interface_name": "tun0", "openvpn_backend": "openvpn"})
    persisted = ConnectionSession(id="session-1", profile_id="profile-1", status=ConnectionStatus.CONNECTING, started_at=datetime.now(timezone.utc))

    rows = monitor.build_rows([profile], {"profile-1": persisted})

    assert rows[0].status == ConnectionStatus.ACTIVE
    assert rows[0].local_ip == "10.8.0.148"
    assert rows[0].gateway == "10.8.0.1"


def test_session_monitor_marks_live_tunnel_active_even_when_runtime_text_is_still_running() -> None:
    monitor = SessionMonitor(
        openvpn_manager=OpenVpnManagerStub(
            [OpenVpnSession(name="rizkan", session_path="/tmp/rizkan.json", status_text="running", backend="openvpn", interface_name="tun")]
        ),
        ppp_manager=PppManagerStub(),
        route_manager=RouteManagerStub(),
        interface_monitor=InterfaceMonitorStub(),
        dns_monitor=DnsMonitorStub(),
        health_monitor=HealthMonitorStub(),
    )
    profile = ConnectionProfile(id="profile-2", name="rizkan", description="test", server_address="vpn-direct.rsudmajalaya.com", protocol=ProtocolType.OPENVPN, config_payload={"interface_name": "tun", "openvpn_backend": "openvpn"})
    persisted = ConnectionSession(id="session-2", profile_id="profile-2", status=ConnectionStatus.CONNECTING, started_at=datetime.now(timezone.utc))

    rows = monitor.build_rows([profile], {"profile-2": persisted})

    assert rows[0].status == ConnectionStatus.ACTIVE
    assert rows[0].interface_name == "tun0"
    assert rows[0].local_ip == "10.8.0.148"


def test_session_monitor_does_not_claim_foreign_tunnel_for_other_profile() -> None:
    monitor = SessionMonitor(
        openvpn_manager=OpenVpnManagerStub(
            [OpenVpnSession(name="rizkan", session_path="/tmp/rizkan.json", status_text="connected", backend="openvpn", interface_name="tun0")]
        ),
        ppp_manager=PppManagerStub(),
        route_manager=RouteManagerStub(),
        interface_monitor=InterfaceMonitorStub(),
        dns_monitor=DnsMonitorStub(),
        health_monitor=HealthMonitorStub(),
    )
    profile = ConnectionProfile(id="profile-1", name="Majalaya", description="test", server_address="103.175.217.180", protocol=ProtocolType.OPENVPN, config_payload={"interface_name": "tun0", "openvpn_backend": "openvpn"})
    persisted = ConnectionSession(id="session-1", profile_id="profile-1", status=ConnectionStatus.INACTIVE, started_at=datetime.now(timezone.utc))

    rows = monitor.build_rows([profile], {"profile-1": persisted})

    assert rows[0].status == ConnectionStatus.INACTIVE
    assert rows[0].local_ip == "-"


def test_session_monitor_keeps_openvpn_running_without_tunnel_as_connecting() -> None:
    monitor = SessionMonitor(
        openvpn_manager=OpenVpnManagerStub(
            [OpenVpnSession(name="Majalaya", session_path="/tmp/majalaya.json", status_text="running", backend="openvpn", interface_name="tun0")]
        ),
        ppp_manager=PppManagerStub(),
        route_manager=RouteManagerStub(),
        interface_monitor=InterfaceMonitorStub(interfaces=[]),
        dns_monitor=DnsMonitorStub(),
        health_monitor=HealthMonitorStub(),
    )
    profile = ConnectionProfile(id="profile-1", name="Majalaya", description="test", server_address="103.175.217.180", protocol=ProtocolType.OPENVPN, config_payload={"interface_name": "tun0", "openvpn_backend": "openvpn"})
    persisted = ConnectionSession(id="session-1", profile_id="profile-1", status=ConnectionStatus.CONNECTING, started_at=datetime.now(timezone.utc))

    rows = monitor.build_rows([profile], {"profile-1": persisted})

    assert rows[0].status == ConnectionStatus.CONNECTING
    assert rows[0].local_ip == "-"


def test_session_monitor_marks_reconnecting_when_runtime_reports_reconnect() -> None:
    monitor = SessionMonitor(
        openvpn_manager=OpenVpnManagerStub(
            [OpenVpnSession(name="Majalaya", session_path="/tmp/majalaya.json", status_text="reconnecting", backend="openvpn", interface_name="tun0")]
        ),
        ppp_manager=PppManagerStub(),
        route_manager=RouteManagerStub(),
        interface_monitor=InterfaceMonitorStub(interfaces=[]),
        dns_monitor=DnsMonitorStub(),
        health_monitor=HealthMonitorStub(),
    )
    profile = ConnectionProfile(id="profile-1", name="Majalaya", description="test", server_address="103.175.217.180", protocol=ProtocolType.OPENVPN, config_payload={"interface_name": "tun0", "openvpn_backend": "openvpn"})
    persisted = ConnectionSession(id="session-1", profile_id="profile-1", status=ConnectionStatus.RECONNECTING, started_at=datetime.now(timezone.utc), reconnect_count=1)

    rows = monitor.build_rows([profile], {"profile-1": persisted})

    assert rows[0].status == ConnectionStatus.RECONNECTING
    assert rows[0].reconnect_count == 1
