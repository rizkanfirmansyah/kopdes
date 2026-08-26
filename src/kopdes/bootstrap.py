from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.event_log import EventLog
from kopdes.infrastructure.config.settings import AppSettings
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
from kopdes.infrastructure.logging.setup import configure_logging
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.infrastructure.system.classic_openvpn_manager import ClassicOpenVpnManager
from kopdes.infrastructure.system.command_runner import CommandRunner
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
from kopdes.shared.enums import EventLevel, ProtocolType
from kopdes.ui.views.main_window import MainWindow
from kopdes.ui.widgets.terminal_panel import TerminalPanel


@dataclass(slots=True)
class BootstrapContext:
    app: QApplication
    window: MainWindow


def build_application(config_path: Path | None = None) -> BootstrapContext:
    settings = (
        AppSettings.from_yaml(config_path)
        if config_path is not None
        else AppSettings.default()
    )
    settings = _normalize_runtime_settings(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level, settings.data_dir)
    bootstrap_database(settings.database_url)

    session_factory = create_session_factory(settings.database_url)
    secret_manager = SecretManager(settings.secret_key_path)
    command_runner = CommandRunner()

    profile_repository = SqlAlchemyConnectionProfileRepository(session_factory)
    session_repository = SqlAlchemyConnectionSessionRepository(session_factory)
    event_repository = SqlAlchemyEventLogRepository(session_factory)

    _seed_demo_data(profile_repository, event_repository, secret_manager, settings.data_dir)

    classic_openvpn_manager = ClassicOpenVpnManager(command_runner, settings.data_dir)
    openvpn3_manager = OpenVpn3Manager(command_runner)
    openvpn_manager = OpenVpnManager(classic_openvpn_manager, openvpn3_manager)
    ppp_manager = PppManager(command_runner)
    route_manager = RouteManager(command_runner)
    session_monitor = SessionMonitor(
        openvpn_manager=openvpn_manager,
        ppp_manager=ppp_manager,
        route_manager=route_manager,
        interface_monitor=InterfaceMonitor(),
        dns_monitor=DnsMonitor(),
        health_monitor=HealthMonitor(command_runner),
    )
    control_center_service = ControlCenterService(
        profile_repository=profile_repository,
        session_repository=session_repository,
        event_repository=event_repository,
        secret_manager=secret_manager,
        config_parser=ConfigImportParser(),
        openvpn_manager=openvpn_manager,
        ppp_manager=ppp_manager,
        route_manager=route_manager,
        session_monitor=session_monitor,
        metrics_collector=SystemMetricsCollector(),
    )

    app = QApplication.instance() or QApplication([])
    terminal_panel = TerminalPanel(command_runner)
    window = MainWindow(
        control_center_service=control_center_service,
        terminal_panel=terminal_panel,
        refresh_interval_ms=settings.refresh_interval_ms,
    )
    return BootstrapContext(app=app, window=window)


def _seed_demo_data(profile_repository, event_repository, secret_manager: SecretManager, data_dir: Path) -> None:
    if profile_repository.list_all():
        return
    openvpn_path = data_dir / "openvpn" / "profiles"
    openvpn_path.mkdir(parents=True, exist_ok=True)
    demo_ovpn = openvpn_path / "OVPN-DC1.ovpn"
    if not demo_ovpn.exists():
        demo_ovpn.write_text(
            "\n".join(
                [
                    "client",
                    "dev tun0",
                    "proto udp",
                    "remote vpn-dc1.example.net 1194",
                ]
            ),
            encoding="utf-8",
        )
    profiles = [
        ConnectionProfile(
            id=str(uuid4()),
            name="OVPN-DC1",
            description="Primary classic OpenVPN datacenter endpoint",
            server_address="vpn-dc1.example.net",
            protocol=ProtocolType.OPENVPN,
            port=1194,
            username="noc-primary",
            encrypted_password=secret_manager.encrypt("change-me"),
            dns_servers=["1.1.1.1", "8.8.8.8"],
            allow_multiple=True,
            tags=["prod", "openvpn"],
            config_payload={
                "interface_name": "tun0",
                "config_path": str(demo_ovpn),
                "openvpn_backend": "openvpn",
            },
        ),
        ConnectionProfile(
            id=str(uuid4()),
            name="L2TP-BRANCH",
            description="Branch office L2TP/IPSec profile",
            server_address="l2tp-branch.example.net",
            protocol=ProtocolType.L2TP_IPSEC,
            username="branch-user",
            encrypted_password=secret_manager.encrypt("change-me"),
            tags=["branch", "backup"],
            config_payload={
                "interface_name": "ppp0",
                "encrypted_ipsec_psk": secret_manager.encrypt("change-me"),
            },
        ),
    ]
    for profile in profiles:
        profile_repository.save(profile)
    event_repository.append(
        EventLog(
            id=str(uuid4()),
            profile_id=None,
            level=EventLevel.INFO,
            event_type="bootstrap",
            message="KOPDES initialized classic OpenVPN aware dashboard state.",
        )
    )


def _normalize_runtime_settings(settings: AppSettings) -> AppSettings:
    if _settings_are_writable(settings):
        return settings
    fallback_dir = Path.home() / ".cache" / "kopdes-recovery"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return AppSettings(
        app_name=settings.app_name,
        database_url=f"sqlite:///{fallback_dir / 'kopdes.db'}",
        log_level=settings.log_level,
        secret_key_path=fallback_dir / "secret.key",
        data_dir=fallback_dir,
        refresh_interval_ms=settings.refresh_interval_ms,
    )


def _settings_are_writable(settings: AppSettings) -> bool:
    return (
        _directory_is_writable(settings.data_dir)
        and _directory_is_writable(settings.secret_key_path.parent)
        and _sqlite_target_is_writable(settings.database_url)
    )


def _sqlite_target_is_writable(database_url: str) -> bool:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return True
    db_path = Path(database_url.removeprefix(prefix))
    return _file_target_is_writable(db_path)


def _directory_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".kopdes-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _file_target_is_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        return os.access(path, os.W_OK)
    except OSError:
        return False
