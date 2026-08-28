from datetime import datetime, timedelta, timezone
from pathlib import Path

from kopdes.application.dtos.connection_profile_dto import ConnectionProfileInput
from kopdes.application.dtos.runtime_state import ActionResult, ConnectionRow
from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.infrastructure.db.models.connection_profile import ConnectionProfileModel
from kopdes.infrastructure.db.models.connection_session import ConnectionSessionModel
from kopdes.infrastructure.db.models.event_log import EventLogModel
from kopdes.infrastructure.db.models.health_check import HealthCheckModel
from kopdes.infrastructure.db.models.route_policy import RoutePolicyModel
from kopdes.infrastructure.db.models.tag import ProfileTagModel, TagModel
from kopdes.infrastructure.db.repositories.connection_profile_repository import (
    SqlAlchemyConnectionProfileRepository,
)
from kopdes.infrastructure.db.repositories.connection_session_repository import (
    SqlAlchemyConnectionSessionRepository,
)
from kopdes.infrastructure.db.repositories.event_log_repository import (
    SqlAlchemyEventLogRepository,
)
from kopdes.infrastructure.db.session import create_session_factory
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.infrastructure.system.classic_openvpn_manager import ClassicOpenVpnManager
from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.config_parser import ConfigImportParser
from kopdes.infrastructure.system.dns_monitor import DnsMonitor
from kopdes.infrastructure.system.health_monitor import HealthMonitor
from kopdes.infrastructure.system.interface_monitor import InterfaceMonitor
from kopdes.infrastructure.system.openvpn3_manager import OpenVpn3Manager
from kopdes.infrastructure.system.openvpn_manager import OpenVpnManager
from kopdes.infrastructure.system.ppp_manager import PppManager
from kopdes.infrastructure.system.route_manager import RouteManager
from kopdes.infrastructure.system.session_monitor import SessionMonitor
from kopdes.infrastructure.system.system_metrics import SystemMetricsCollector
from kopdes.shared.enums import ConnectionStatus, ProtocolType


class NullRunner:
    def run(self, command, timeout=30):
        return CommandResult(command=command, return_code=1, stdout="", stderr="not available")


def build_service(tmp_path: Path) -> ControlCenterService:
    database_url = f"sqlite:///{tmp_path / 'kopdes.db'}"
    bootstrap_database(database_url)
    session_factory = create_session_factory(database_url)
    runner = NullRunner()
    openvpn_manager = OpenVpnManager(
        ClassicOpenVpnManager(runner, tmp_path),
        OpenVpn3Manager(runner),
    )
    return ControlCenterService(
        SqlAlchemyConnectionProfileRepository(session_factory),
        SqlAlchemyConnectionSessionRepository(session_factory),
        SqlAlchemyEventLogRepository(session_factory),
        SecretManager(tmp_path / "secret.key"),
        ConfigImportParser(),
        openvpn_manager,
        PppManager(runner),
        RouteManager(runner),
        SessionMonitor(
            openvpn_manager,
            PppManager(runner),
            RouteManager(runner),
            InterfaceMonitor(),
            DnsMonitor(tmp_path / "resolv.conf"),
            HealthMonitor(runner),
        ),
        SystemMetricsCollector(),
    )


def test_control_center_service_saves_and_lists_profiles(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.save_profile(
        ConnectionProfileInput(
            name="VPN-TEST",
            description="service test",
            server_address="vpn.example.net",
            protocol=ProtocolType.OPENVPN,
            username="tester",
            password="secret",
            config_payload={"openvpn_backend": "openvpn"},
        )
    )
    rows = service.list_connection_rows()
    assert rows[0].name == "VPN-TEST"
    assert rows[0].backend == "openvpn"


def test_control_center_service_encrypts_ipsec_psk_in_config_payload(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="L2TP-TEST",
            description="ipsec secret test",
            server_address="l2tp.example.net",
            protocol=ProtocolType.L2TP_IPSEC,
            username="tester",
            password="vpn-pass",
            config_payload={"ipsec_psk": "super-psk"},
        )
    )
    assert "ipsec_psk" not in profile.config_payload
    assert profile.config_payload["encrypted_ipsec_psk"] != "super-psk"


def test_control_center_service_preview_detects_auth_user_pass(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    ovpn_path = tmp_path / "auth.ovpn"
    ovpn_path.write_text(
        "client\nremote vpn.example.net 1194\nauth-user-pass\ndev tun0\n",
        encoding="utf-8",
    )

    preview = service.preview_ovpn_import(ovpn_path, "Auth VPN")

    assert preview["auth_user_pass_required"] is True
    assert preview["auth_user_pass_file"] is None


def test_control_center_service_inspector_includes_openvpn_runtime_logs(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Majalaya",
            description="runtime log test",
            server_address="103.175.217.180",
            protocol=ProtocolType.OPENVPN,
            username="tester",
            password="secret",
            config_payload={"openvpn_backend": "openvpn", "interface_name": "tun0"},
        )
    )
    runtime_dir = tmp_path / "openvpn" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "Majalaya.log").write_text(
        "Initialization Sequence Completed\nPING restart\n",
        encoding="utf-8",
    )

    inspector = service.get_connection_inspector(profile.id)

    assert inspector is not None
    assert "=== KOPDES Events ===" in inspector.log_messages
    assert "=== OpenVPN Runtime ===" in inspector.log_messages
    assert any("Initialization Sequence Completed" in line for line in inspector.log_messages)


def test_control_center_service_marks_stalled_connect_as_failed_after_timeout(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Slow VPN",
            description="timeout test",
            server_address="203.0.113.10",
            protocol=ProtocolType.OPENVPN,
            username="tester",
            password="secret",
            config_payload={"openvpn_backend": "openvpn", "interface_name": "tun0"},
        )
    )
    stale_session = ConnectionSession(
        id="session-timeout",
        profile_id=profile.id,
        status=ConnectionStatus.CONNECTING,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=11),
    )
    service._session_repository.save(stale_session)

    def fake_build_rows(profiles, latest_sessions):
        current = latest_sessions[profile.id]
        return [
            ConnectionRow(
                profile_id=profile.id,
                status=current.status,
                name=profile.name,
                protocol=profile.protocol.value,
                server=profile.server_address,
                backend="openvpn",
            )
        ]

    monkeypatch.setattr(service._session_monitor, "build_rows", fake_build_rows)
    monkeypatch.setattr(
        service._openvpn_manager,
        "disconnect_profile",
        lambda runtime_profile: ActionResult(True, "Disconnected timed out runtime."),
    )

    rows = service.list_connection_rows()
    latest = service._latest_sessions_by_profile()[profile.id]

    assert rows[0].status == ConnectionStatus.FAILED
    assert latest.status == ConnectionStatus.FAILED
    assert latest.last_error == "Connection exceeded 10 seconds without reaching a connected state."


def test_control_center_service_reconnect_marks_session_as_reconnecting(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Retry VPN",
            description="reconnect test",
            server_address="198.51.100.20",
            protocol=ProtocolType.OPENVPN,
            username="tester",
            password="secret",
            config_payload={"openvpn_backend": "openvpn", "interface_name": "tun0"},
        )
    )
    service._session_repository.save(
        ConnectionSession(
            id="session-previous",
            profile_id=profile.id,
            status=ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            reconnect_count=1,
        )
    )
    monkeypatch.setattr(service, "disconnect_profile", lambda profile_id: ActionResult(True, "Disconnected."))
    monkeypatch.setattr(
        service._openvpn_manager,
        "start_session",
        lambda runtime_profile, password=None: ActionResult(True, "Started reconnect."),
    )

    result = service.reconnect_profile(profile.id)
    latest = service._latest_sessions_by_profile()[profile.id]

    assert result.success is True
    assert latest.status == ConnectionStatus.RECONNECTING
    assert latest.reconnect_count == 2



def test_control_center_service_reconnect_does_not_start_after_failed_disconnect(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Unsafe Retry",
            description="reconnect safety test",
            server_address="198.51.100.30",
            protocol=ProtocolType.OPENVPN,
        )
    )
    starts: list[str] = []
    monkeypatch.setattr(
        service,
        "disconnect_profile",
        lambda profile_id: ActionResult(False, "Disconnect failed.", "process still running"),
    )
    monkeypatch.setattr(
        service._openvpn_manager,
        "start_session",
        lambda runtime_profile, password=None: starts.append(runtime_profile.name) or ActionResult(True, "started"),
    )

    result = service.reconnect_profile(profile.id)
    latest = service._latest_sessions_by_profile()[profile.id]

    assert result.success is False
    assert starts == []
    assert latest.status == ConnectionStatus.FAILED
    assert "could not be stopped" in result.message


def test_control_center_service_promotes_runtime_connected_state(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Runtime State",
            description="state reconciliation test",
            server_address="198.51.100.40",
            protocol=ProtocolType.OPENVPN,
            config_payload={"openvpn_backend": "openvpn", "interface_name": "tun0"},
        )
    )
    service._session_repository.save(
        ConnectionSession(
            id="pending-state",
            profile_id=profile.id,
            status=ConnectionStatus.CONNECTING,
            started_at=datetime.now(timezone.utc),
        )
    )
    monkeypatch.setattr(
        service._session_monitor,
        "build_rows",
        lambda profiles, latest: [
            ConnectionRow(
                profile_id=profile.id,
                status=ConnectionStatus.ACTIVE,
                name=profile.name,
                protocol=profile.protocol.value,
                server=profile.server_address,
                backend="openvpn",
                local_ip="10.8.0.2",
            )
        ],
    )

    rows = service.list_connection_rows()
    latest = service._latest_sessions_by_profile()[profile.id]

    assert rows[0].status == ConnectionStatus.ACTIVE
    assert latest.status == ConnectionStatus.ACTIVE


def test_control_center_service_duplicate_import_does_not_touch_system_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = build_service(tmp_path)
    service.save_profile(
        ConnectionProfileInput(
            name="DUPLICATE",
            description="existing profile",
            server_address="vpn.example.net",
            protocol=ProtocolType.OPENVPN,
        )
    )
    source = tmp_path / "new.ovpn"
    source.write_text("client\nremote vpn.example.net 1194\n", encoding="utf-8")
    called = False

    def should_not_import(*args, **kwargs):
        nonlocal called
        called = True
        return ActionResult(True, "unexpected")

    monkeypatch.setattr(service._openvpn_manager, "import_config", should_not_import)

    result = service.import_ovpn(source, "DUPLICATE")

    assert result.success is False
    assert "already exists" in result.message
    assert called is False
    assert not (tmp_path / "openvpn" / "profiles" / "DUPLICATE.ovpn").exists()


def test_control_center_service_rejects_connect_when_session_is_active(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="ACTIVE-CONNECTION",
            description="state guard",
            server_address="vpn.example.net",
            protocol=ProtocolType.OPENVPN,
        )
    )
    service._session_repository.save(
        ConnectionSession(
            id="active-session",
            profile_id=profile.id,
            status=ConnectionStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
        )
    )
    called = False

    def should_not_start(*args, **kwargs):
        nonlocal called
        called = True
        return ActionResult(True, "unexpected")

    monkeypatch.setattr(service._openvpn_manager, "start_session", should_not_start)

    result = service.connect_profile(profile.id)

    assert result.success is False
    assert result.message == "Connection is already active."
    assert called is False


def test_control_center_service_auto_recovery_is_bounded(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    profile = service.save_profile(
        ConnectionProfileInput(
            name="Retry Limit",
            description="bounded recovery test",
            server_address="vpn.example.net",
            protocol=ProtocolType.OPENVPN,
            auto_reconnect=True,
        )
    )
    failure_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    service._session_repository.save(
        ConnectionSession(
            id="retry-limit-session",
            profile_id=profile.id,
            status=ConnectionStatus.FAILED,
            started_at=failure_time,
            ended_at=failure_time,
            reconnect_count=service.MAX_AUTO_RETRIES,
        )
    )
    attempted = False

    def should_not_reconnect(_profile_id: str):
        nonlocal attempted
        attempted = True
        return ActionResult(False, "unexpected")

    monkeypatch.setattr(service, "reconnect_profile", should_not_reconnect)

    result = service.recover_failed_connections()

    assert result.success is True
    assert attempted is False
