from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from kopdes.application.dtos.connection_profile_dto import (
    ConnectionProfileInput,
    DashboardStats,
    PortMappingInput,
)
from kopdes.application.dtos.runtime_state import (
    ActionResult,
    ConnectionInspector,
    ConnectionRow,
    PortMappingRow,
)
from kopdes.application.ports.repositories import (
    ConnectionProfileRepository,
    ConnectionSessionRepository,
    EventLogRepository,
    PortMappingRepository,
)
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.domain.entities.event_log import EventLog
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.infrastructure.system.config_parser import ConfigImportParser
from kopdes.infrastructure.system.system_metrics import SystemMetrics, SystemMetricsCollector
from kopdes.shared.enums import ConnectionStatus, EventLevel, ProtocolType


LOGGER = logging.getLogger(__name__)


class ControlCenterService:
    CONNECT_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        profile_repository: ConnectionProfileRepository,
        session_repository: ConnectionSessionRepository,
        event_repository: EventLogRepository,
        secret_manager: SecretManager,
        config_parser: ConfigImportParser,
        openvpn_manager,
        ppp_manager,
        route_manager,
        session_monitor,
        metrics_collector: SystemMetricsCollector,
        port_mapping_repository: PortMappingRepository | None = None,
        ssh_tunnel_manager=None,
    ) -> None:
        self._profile_repository = profile_repository
        self._session_repository = session_repository
        self._event_repository = event_repository
        self._secret_manager = secret_manager
        self._config_parser = config_parser
        self._openvpn_manager = openvpn_manager
        self._ppp_manager = ppp_manager
        self._route_manager = route_manager
        self._session_monitor = session_monitor
        self._metrics_collector = metrics_collector
        self._port_mapping_repository = port_mapping_repository
        self._ssh_tunnel_manager = ssh_tunnel_manager

    def get_dashboard_stats(self) -> DashboardStats:
        rows = self.list_connection_rows()
        try:
            metrics = self._metrics_collector.collect()
        except Exception:
            LOGGER.exception("System metrics collection failed")
            metrics = SystemMetrics(0.0, 0.0, 0.0)
        active = sum(1 for row in rows if row.status == ConnectionStatus.ACTIVE)
        failed = sum(1 for row in rows if row.status == ConnectionStatus.FAILED)
        return DashboardStats(
            total_connections=len(rows),
            active_connections=active,
            failed_connections=failed,
            bandwidth_usage_mbps=metrics.bandwidth_usage_mbps,
            system_load=metrics.system_load,
            memory_usage_percent=metrics.memory_usage_percent,
        )

    def list_connection_rows(self) -> list[ConnectionRow]:
        try:
            profiles = self._profile_repository.list_all()
            latest_sessions = self._latest_sessions_by_profile()
            rows = self._session_monitor.build_rows(profiles, latest_sessions)
            latest_sessions, changed = self._expire_stale_pending_sessions(profiles, latest_sessions, rows)
            if changed:
                rows = self._session_monitor.build_rows(profiles, latest_sessions)
            return rows
        except Exception:
            LOGGER.exception("Runtime monitoring failed while building connection rows")
            return []

    def get_profile(self, profile_id: str) -> ConnectionProfile | None:
        return self._profile_repository.get_by_id(profile_id)

    def get_port_mapping(self, mapping_id: str) -> PortMapping | None:
        if self._port_mapping_repository is None:
            return None
        return self._port_mapping_repository.get_by_id(mapping_id)

    def validate_port_mapping_input(
        self,
        data: PortMappingInput,
        mapping_id: str | None = None,
    ) -> list[str]:
        errors: list[str] = []
        name = str(data.name or "").strip()
        if self._port_mapping_repository is None:
            return ["SSH port mapping storage is not available."]
        if not name:
            errors.append("Mapping name is required.")
        elif len(name) > 255:
            errors.append("Mapping name must be 255 characters or fewer.")
        elif any(ord(char) < 32 for char in name):
            errors.append("Mapping name contains control characters.")

        for label, value in (
            ("SSH host", data.ssh_host),
            ("SSH username", data.ssh_username),
            ("Local host", data.local_host),
            ("Remote host", data.remote_host),
        ):
            text_value = str(value or "").strip()
            if not text_value:
                errors.append(f"{label} is required.")
            elif any(char in text_value for char in "\r\n\x00"):
                errors.append(f"{label} contains an invalid control character.")

        for label, value in (
            ("SSH port", data.ssh_port),
            ("Local port", data.local_port),
            ("Remote port", data.remote_port),
        ):
            try:
                valid = 1 <= int(value) <= 65535
            except (TypeError, ValueError):
                valid = False
            if not valid:
                errors.append(f"{label} must be between 1 and 65535.")
        try:
            if int(data.local_port) < 1024:
                errors.append("Local port must be 1024 or higher so KOPDES does not require root for SSH.")
        except (TypeError, ValueError):
            pass

        if data.identity_file:
            identity = Path(data.identity_file).expanduser()
            if not identity.is_file():
                errors.append(f"SSH identity file does not exist: {identity}")

        duplicate = self._port_mapping_repository.get_by_name(name) if name else None
        if duplicate is not None and duplicate.id != mapping_id:
            errors.append(f"A port mapping named '{name}' already exists.")
        return errors

    def save_port_mapping(
        self,
        data: PortMappingInput,
        mapping_id: str | None = None,
    ) -> PortMapping:
        errors = self.validate_port_mapping_input(data, mapping_id)
        if errors:
            raise ValueError("Cannot save SSH port mapping:\n- " + "\n- ".join(errors))
        if self._port_mapping_repository is None:
            raise RuntimeError("SSH port mapping storage is not available.")
        existing = self._port_mapping_repository.get_by_id(mapping_id) if mapping_id else None
        encrypted_password = existing.encrypted_password if existing else None
        if data.password:
            encrypted_password = self._secret_manager.encrypt(data.password)
        mapping = PortMapping(
            id=existing.id if existing else str(uuid4()),
            name=str(data.name).strip(),
            description=str(data.description or "").strip(),
            ssh_host=str(data.ssh_host).strip(),
            ssh_port=int(data.ssh_port),
            ssh_username=str(data.ssh_username).strip(),
            local_host=str(data.local_host).strip(),
            local_port=int(data.local_port),
            remote_host=str(data.remote_host).strip(),
            remote_port=int(data.remote_port),
            identity_file=str(data.identity_file).strip() if data.identity_file else None,
            encrypted_password=encrypted_password,
            auto_reconnect=bool(data.auto_reconnect),
            enabled=bool(data.enabled),
            last_error=existing.last_error if existing else None,
            last_started_at=existing.last_started_at if existing else None,
            last_stopped_at=existing.last_stopped_at if existing else None,
            created_at=existing.created_at if existing else None,
            updated_at=datetime.now(timezone.utc),
        )
        saved = self._port_mapping_repository.save(mapping)
        self._append_event(None, EventLevel.INFO, "port_mapping.save", f"Saved SSH mapping '{saved.name}'.")
        return saved

    def list_port_mapping_rows(self) -> list[PortMappingRow]:
        if self._port_mapping_repository is None:
            return []
        try:
            mappings = self._port_mapping_repository.list_all()
            sessions = self._ssh_tunnel_manager.list_sessions() if self._ssh_tunnel_manager else []
        except Exception:
            LOGGER.exception("SSH port mapping monitoring failed")
            return []
        sessions_by_id = {session.mapping_id: session for session in sessions}
        rows: list[PortMappingRow] = []
        for mapping in mappings:
            session = sessions_by_id.get(mapping.id)
            if session is not None:
                status = ConnectionStatus.ACTIVE if session.local_listening else ConnectionStatus.CONNECTING
                pid = session.pid
                error = session.last_error or mapping.last_error or "-"
            else:
                process_was_started = (
                    mapping.last_started_at is not None
                    and (
                        mapping.last_stopped_at is None
                        or mapping.last_started_at > mapping.last_stopped_at
                    )
                )
                status = (
                    ConnectionStatus.FAILED
                    if mapping.last_error or process_was_started
                    else ConnectionStatus.INACTIVE
                )
                pid = None
                error = mapping.last_error or (
                    "Managed SSH process is not running." if process_was_started else "-"
                )
            rows.append(
                PortMappingRow(
                    mapping_id=mapping.id,
                    status=status,
                    name=mapping.name,
                    local_endpoint=f"{mapping.local_host}:{mapping.local_port}",
                    remote_endpoint=f"{mapping.remote_host}:{mapping.remote_port}",
                    ssh_target=f"{mapping.ssh_username}@{mapping.ssh_host}:{mapping.ssh_port}",
                    pid=pid,
                    duration_text=self._mapping_duration(mapping) if session else "-",
                    last_error=error,
                )
            )
        return rows

    def connect_port_mapping(self, mapping_id: str) -> ActionResult:
        mapping = self._require_port_mapping(mapping_id)
        if self._ssh_tunnel_manager is None:
            return ActionResult(False, "SSH tunnel manager is not available.")
        try:
            password = self._decrypt_port_mapping_password(mapping)
            result = self._ssh_tunnel_manager.start(mapping, password)
        except Exception as exc:
            LOGGER.exception("SSH mapping start failed for %s", mapping.name)
            result = ActionResult(False, "SSH port mapping could not be started.", self._safe_error(exc))
        mapping.last_started_at = datetime.now(timezone.utc)
        mapping.last_error = None if result.success else (result.details or result.message)
        self._save_port_mapping_state(mapping)
        self._append_event(
            None,
            EventLevel.INFO if result.success else EventLevel.ERROR,
            "port_mapping.connect",
            result.message,
            result.details,
        )
        return result

    def disconnect_port_mapping(self, mapping_id: str) -> ActionResult:
        mapping = self._require_port_mapping(mapping_id)
        if self._ssh_tunnel_manager is None:
            return ActionResult(False, "SSH tunnel manager is not available.")
        try:
            result = self._ssh_tunnel_manager.stop(mapping.id)
        except Exception as exc:
            LOGGER.exception("SSH mapping stop failed for %s", mapping.name)
            result = ActionResult(False, "SSH port mapping could not be stopped.", self._safe_error(exc))
        mapping.last_stopped_at = datetime.now(timezone.utc)
        mapping.last_error = None if result.success else (result.details or result.message)
        self._save_port_mapping_state(mapping)
        self._append_event(
            None,
            EventLevel.INFO if result.success else EventLevel.ERROR,
            "port_mapping.disconnect",
            result.message,
            result.details,
        )
        return result

    def delete_port_mapping(self, mapping_id: str) -> ActionResult:
        mapping = self._require_port_mapping(mapping_id)
        if self._ssh_tunnel_manager is None or self._port_mapping_repository is None:
            return ActionResult(False, "SSH port mapping services are not available.")
        try:
            stop_result = self._ssh_tunnel_manager.stop(mapping.id)
        except Exception as exc:
            LOGGER.exception("SSH mapping cleanup failed before delete for %s", mapping.name)
            return ActionResult(False, "SSH port mapping could not be deleted.", self._safe_error(exc))
        if not stop_result.success:
            return ActionResult(False, "SSH port mapping could not be deleted while it is running.", stop_result.details)
        self._port_mapping_repository.delete(mapping.id)
        self._append_event(None, EventLevel.INFO, "port_mapping.delete", f"Deleted SSH mapping '{mapping.name}'.")
        return ActionResult(True, f"SSH port mapping '{mapping.name}' deleted.")

    def validate_profile_input(
        self,
        data: ConnectionProfileInput,
        profile_id: str | None = None,
    ) -> list[str]:
        errors: list[str] = []
        try:
            protocol = data.protocol if isinstance(data.protocol, ProtocolType) else ProtocolType(str(data.protocol))
        except (TypeError, ValueError):
            protocol = None
            errors.append("Protocol is invalid.")

        name = str(data.name or "").strip()
        server = str(data.server_address or "").strip()
        payload = data.config_payload if isinstance(data.config_payload, dict) else {}
        if not name:
            errors.append("Connection name is required.")
        elif len(name) > 255:
            errors.append("Connection name must be 255 characters or fewer.")
        elif any(ord(char) < 32 for char in name):
            errors.append("Connection name contains control characters.")

        if protocol != ProtocolType.PPPOE and not server:
            if protocol != ProtocolType.PPP or not str(payload.get("peer_name", "")).strip():
                errors.append("Server address is required for this protocol.")
        if any(char in server for char in "\r\n"):
            errors.append("Server address contains an invalid newline.")

        if data.port is not None and not 1 <= int(data.port) <= 65535:
            errors.append("Port must be between 1 and 65535.")
        if not 1 <= int(data.route_metric) <= 9999:
            errors.append("Route metric must be between 1 and 9999.")
        if data.mtu is not None and not 576 <= int(data.mtu) <= 9200:
            errors.append("MTU must be between 576 and 9200.")
        if data.keepalive is not None and not 0 <= int(data.keepalive) <= 3600:
            errors.append("Keepalive must be between 0 and 3600 seconds.")

        if protocol in {ProtocolType.PPPOE, ProtocolType.PPTP, ProtocolType.L2TP, ProtocolType.L2TP_IPSEC}:
            if not str(data.username or "").strip():
                errors.append("Username is required for this protocol.")
        config_path = str(payload.get("config_path", "")).strip()
        if protocol == ProtocolType.OPENVPN and config_path and not Path(config_path).expanduser().is_file():
            errors.append("The selected OpenVPN config file does not exist.")

        duplicate = self._profile_repository.get_by_name(name) if name else None
        if duplicate is not None and duplicate.id != profile_id:
            errors.append(f"A connection named '{name}' already exists.")
        return errors

    def save_profile(
        self,
        data: ConnectionProfileInput,
        profile_id: str | None = None,
    ) -> ConnectionProfile:
        errors = self.validate_profile_input(data, profile_id)
        if errors:
            raise ValueError("Cannot save connection profile:\n- " + "\n- ".join(errors))
        existing = self._profile_repository.get_by_id(profile_id) if profile_id else None
        protocol = data.protocol if isinstance(data.protocol, ProtocolType) else ProtocolType(str(data.protocol))
        name = str(data.name).strip()
        server = str(data.server_address or "").strip()
        encrypted_password = existing.encrypted_password if existing else None
        if data.password:
            encrypted_password = self._secret_manager.encrypt(data.password)
        config_payload = self._prepare_config_payload(existing, data.config_payload)
        if protocol == ProtocolType.OPENVPN:
            config_payload.setdefault("openvpn_backend", str(config_payload.get("openvpn_backend", "openvpn")))
            if data.username or encrypted_password:
                config_payload.setdefault("auth_user_pass_required", True)
        profile = ConnectionProfile(
            id=existing.id if existing else str(uuid4()),
            name=name,
            description=str(data.description or "").strip(),
            server_address=server,
            protocol=protocol,
            port=data.port,
            username=str(data.username).strip() if data.username else None,
            encrypted_password=encrypted_password,
            route_metric=data.route_metric,
            dns_servers=[str(item).strip() for item in data.dns_servers if str(item).strip()],
            mtu=data.mtu,
            keepalive=data.keepalive,
            auto_reconnect=data.auto_reconnect,
            allow_multiple=data.allow_multiple,
            tags=[str(item).strip() for item in data.tags if str(item).strip()],
            config_payload=config_payload,
            created_at=existing.created_at if existing else None,
            updated_at=datetime.now(timezone.utc),
        )
        saved = self._profile_repository.save(profile)
        self._append_event(saved.id, EventLevel.INFO, "profile.save", f"Saved profile '{saved.name}'.")
        return saved

    def preview_ovpn_import(self, path: Path, alias: str) -> dict[str, object]:
        payload = self._config_parser.parse(path)
        config_payload = dict(payload.get("config_payload", {}))
        return {
            "name": alias,
            "description": str(payload.get("description", "Imported OpenVPN profile")),
            "server_address": str(payload.get("server_address", "")),
            "port": payload.get("port") if isinstance(payload.get("port"), int) else None,
            "username": str(payload.get("username", "") or "") or None,
            "auth_user_pass_required": self._config_bool(config_payload.get("auth_user_pass_required")),
            "auth_user_pass_file": str(config_payload.get("auth_user_pass_file", "") or "") or None,
            "warnings": list(payload.get("warnings", [])),
            "errors": list(payload.get("errors", [])),
            "config_payload": config_payload,
        }

    def import_ovpn(
        self,
        path: Path,
        alias: str,
        username: str | None = None,
        password: str | None = None,
    ) -> ActionResult:
        preview = self.preview_ovpn_import(path, alias)
        preview_errors = [str(item) for item in preview.get("errors", []) if str(item).strip()]
        if preview_errors:
            return ActionResult(False, "OpenVPN import validation failed.", "\n".join(preview_errors))
        import_result = self._openvpn_manager.import_config(str(path), alias, preferred_backend="openvpn")
        if not import_result.success:
            return import_result
        config_payload = dict(preview["config_payload"])
        config_payload.update(import_result.data)
        profile = self.save_profile(
            ConnectionProfileInput(
                name=alias,
                description=str(preview["description"]),
                server_address=str(preview["server_address"]),
                protocol=ProtocolType.OPENVPN,
                port=preview["port"] if isinstance(preview["port"], int) else None,
                username=username or preview["username"],
                password=password,
                route_metric=100,
                dns_servers=[],
                mtu=None,
                keepalive=None,
                auto_reconnect=True,
                allow_multiple=True,
                tags=self._import_tags(config_payload),
                config_payload=config_payload,
            )
        )
        detail_parts = [import_result.details] if import_result.details else []
        preview_warnings = [str(item) for item in preview.get("warnings", []) if str(item).strip()]
        if self._config_bool(config_payload.get("auth_user_pass_required")) and not password:
            preview_warnings.append("Username/password are still required before connecting.")
        if preview_warnings:
            detail_parts.append("Warnings:\n- " + "\n- ".join(preview_warnings))
        details = "\n\n".join(part for part in detail_parts if part) or None
        self._append_event(profile.id, EventLevel.INFO, "openvpn.import", import_result.message, details)
        return ActionResult(True, import_result.message, details, {"profile_id": profile.id, **import_result.data})

    def connect_profile(self, profile_id: str) -> ActionResult:
        profile = self._require_profile(profile_id)
        latest = self._latest_sessions_by_profile().get(profile.id)
        try:
            runtime_profile = self._build_runtime_profile(profile)
            password = self._decrypt_password(profile)
            if profile.protocol == ProtocolType.OPENVPN:
                result = self._openvpn_manager.start_session(runtime_profile, password)
            else:
                result = self._ppp_manager.connect(runtime_profile, password)
        except Exception as exc:
            LOGGER.exception("Connection start failed for %s", profile.name)
            result = ActionResult(False, "Connection could not be started.", self._safe_error(exc))
        session = ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.CONNECTING if result.success else ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            reconnect_count=latest.reconnect_count if latest else 0,
            last_error=None if result.success else (result.details or result.message),
        )
        self._save_session(session)
        self._append_event(
            profile.id,
            EventLevel.INFO if result.success else EventLevel.ERROR,
            "connection.connect",
            result.message,
            result.details,
        )
        return result

    def disconnect_profile(self, profile_id: str) -> ActionResult:
        profile = self._require_profile(profile_id)
        try:
            if profile.protocol == ProtocolType.OPENVPN:
                result = self._openvpn_manager.disconnect_profile(profile)
            else:
                result = self._ppp_manager.disconnect(profile)
        except Exception as exc:
            LOGGER.exception("Connection stop failed for %s", profile.name)
            result = ActionResult(False, "Connection could not be stopped.", self._safe_error(exc))
        session = ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.DISCONNECTING if result.success else ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc) if result.success else None,
            last_error=None if result.success else (result.details or result.message),
        )
        self._save_session(session)
        self._append_event(
            profile.id,
            EventLevel.INFO if result.success else EventLevel.ERROR,
            "connection.disconnect",
            result.message,
            result.details,
        )
        return result

    def reconnect_profile(self, profile_id: str) -> ActionResult:
        profile = self._require_profile(profile_id)
        latest = self._latest_sessions_by_profile().get(profile_id)
        disconnect = self.disconnect_profile(profile_id)
        runtime_profile = self._build_runtime_profile(profile)
        password = self._decrypt_password(profile)
        if profile.protocol == ProtocolType.OPENVPN:
            connect = self._openvpn_manager.start_session(runtime_profile, password)
        else:
            connect = self._ppp_manager.connect(runtime_profile, password)
        reconnect_count = (latest.reconnect_count if latest else 0) + 1
        session = ConnectionSession(
            id=str(uuid4()),
            profile_id=profile_id,
            status=ConnectionStatus.RECONNECTING if connect.success else ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            reconnect_count=reconnect_count,
            last_error=None if connect.success else (connect.details or connect.message),
        )
        self._save_session(session)
        self._append_event(
            profile_id,
            EventLevel.INFO if connect.success else EventLevel.ERROR,
            "connection.reconnect",
            connect.message,
            connect.details,
        )
        if connect.success:
            return connect
        detail_parts = [disconnect.message]
        if disconnect.details:
            detail_parts.append(disconnect.details)
        if connect.details:
            detail_parts.append(connect.details)
        return ActionResult(False, connect.message, "; ".join(part for part in detail_parts if part))

    def delete_profile(self, profile_id: str) -> ActionResult:
        profile = self._require_profile(profile_id)
        external_result = ActionResult(True, "Profile deleted from KOPDES.")
        if profile.protocol == ProtocolType.OPENVPN:
            external_result = self._openvpn_manager.remove_profile(profile)
        elif profile.protocol in {
            ProtocolType.PPP,
            ProtocolType.PPPOE,
            ProtocolType.PPTP,
            ProtocolType.L2TP,
            ProtocolType.L2TP_IPSEC,
        }:
            external_result = self._ppp_manager.delete(profile)
        if not external_result.success:
            self._append_event(profile_id, EventLevel.ERROR, "profile.delete", external_result.message, external_result.details)
            return external_result
        self._profile_repository.delete(profile_id)
        self._append_event(profile_id, EventLevel.INFO, "profile.delete", external_result.message, external_result.details)
        return external_result

    def shutdown(self) -> ActionResult:
        """Stop all sessions owned by KOPDES without creating new pending sessions."""
        failures: list[str] = []
        try:
            profiles = self._profile_repository.list_all()
        except Exception as exc:
            LOGGER.exception("Could not load profiles during shutdown")
            profiles = []
            failures.append(f"Profiles: {self._safe_error(exc)}")

        if self._ssh_tunnel_manager is not None:
            try:
                mappings = self._port_mapping_repository.list_all() if self._port_mapping_repository else []
                result = self._ssh_tunnel_manager.shutdown(mappings)
            except Exception as exc:
                LOGGER.exception("SSH port mapping shutdown failed")
                failures.append(f"SSH port mappings: {self._safe_error(exc)}")
            else:
                if not result.success:
                    failures.append(f"SSH port mappings: {result.details or result.message}")

        managers = (
            (self._openvpn_manager, "OpenVPN"),
            (self._ppp_manager, "PPP"),
        )
        for manager, label in managers:
            shutdown = getattr(manager, "shutdown", None)
            if callable(shutdown):
                try:
                    result = shutdown(profiles)
                except Exception as exc:
                    LOGGER.exception("%s shutdown failed", label)
                    failures.append(f"{label}: {self._safe_error(exc)}")
                else:
                    if not result.success:
                        failures.append(f"{label}: {result.details or result.message}")
                continue
            for profile in profiles:
                if (label == "OpenVPN") != (profile.protocol == ProtocolType.OPENVPN):
                    continue
                try:
                    result = self._disconnect_runtime_profile(profile)
                except Exception as exc:
                    failures.append(f"{profile.name}: {self._safe_error(exc)}")
                else:
                    if not result.success:
                        failures.append(f"{profile.name}: {result.details or result.message}")

        if failures:
            message = "KOPDES closed, but some managed connections may still be running."
            details = "\n".join(failures)
            LOGGER.error("%s %s", message, details)
            return ActionResult(False, message, details)
        LOGGER.info("KOPDES shutdown completed; managed connections stopped.")
        return ActionResult(True, "Stopped all managed connections.")

    def get_connection_inspector(self, profile_id: str) -> ConnectionInspector | None:
        profile = self._profile_repository.get_by_id(profile_id)
        if profile is None:
            return None
        row = next((item for item in self.list_connection_rows() if item.profile_id == profile_id), None)
        if row is None:
            return None
        logs = self._build_inspector_logs(profile)
        return self._session_monitor.build_inspector(profile, row, logs)

    def add_route(
        self,
        destination: str,
        gateway: str | None = None,
        device: str | None = None,
        metric: int | None = None,
        table: str | None = None,
    ) -> ActionResult:
        return self._route_manager.add_route(destination, gateway, device, metric, table)

    def delete_route(self, destination: str, table: str | None = None) -> ActionResult:
        return self._route_manager.delete_route(destination, table)

    def change_route_metric(
        self,
        destination: str,
        metric: int,
        gateway: str | None = None,
        device: str | None = None,
        table: str | None = None,
    ) -> ActionResult:
        return self._route_manager.change_metric(destination, metric, gateway, device, table)

    def list_logs(self, profile_id: str | None = None, limit: int = 200) -> list[str]:
        try:
            events = self._event_repository.list_recent(limit)
        except Exception:
            LOGGER.exception("Could not read application logs")
            return ["Log storage is temporarily unavailable."]
        filtered = [item for item in events if profile_id is None or item.profile_id == profile_id]
        return [
            f"[{item.created_at}] {item.level.value.upper()} {item.event_type}: {item.message}"
            for item in reversed(filtered)
        ]

    def _append_event(
        self,
        profile_id: str | None,
        level: EventLevel,
        event_type: str,
        message: str,
        details: str | None = None,
    ) -> None:
        try:
            self._event_repository.append(
                EventLog(
                    id=str(uuid4()),
                    profile_id=profile_id,
                    level=level,
                    event_type=event_type,
                    message=message,
                    details=details,
                )
            )
        except Exception:
            LOGGER.exception("Could not persist event %s", event_type)

    def _save_session(self, session: ConnectionSession) -> ConnectionSession:
        try:
            return self._session_repository.save(session)
        except Exception:
            LOGGER.exception("Could not persist session state for %s", session.profile_id)
            return session

    def _latest_sessions_by_profile(self) -> dict[str, ConnectionSession]:
        latest: dict[str, ConnectionSession] = {}
        for session in self._session_repository.list_latest():
            if session.profile_id not in latest:
                latest[session.profile_id] = session
        return latest

    def _expire_stale_pending_sessions(
        self,
        profiles: list[ConnectionProfile],
        latest_sessions: dict[str, ConnectionSession],
        rows: list[ConnectionRow],
    ) -> tuple[dict[str, ConnectionSession], bool]:
        profiles_by_id = {profile.id: profile for profile in profiles}
        now = datetime.now(timezone.utc)
        changed = False

        for row in rows:
            session = latest_sessions.get(row.profile_id)
            if session is None or session.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING}:
                continue
            if row.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING}:
                continue
            if session.started_at is None:
                continue

            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if now - started_at < timedelta(seconds=self.CONNECT_TIMEOUT_SECONDS):
                continue

            profile = profiles_by_id.get(row.profile_id)
            if profile is None:
                continue

            try:
                disconnect_result = self._disconnect_runtime_profile(profile)
            except Exception as exc:
                LOGGER.exception("Timeout cleanup failed for %s", profile.name)
                disconnect_result = ActionResult(False, "Timeout cleanup failed.", self._safe_error(exc))
            timeout_message = (
                f"Connection exceeded {self.CONNECT_TIMEOUT_SECONDS} seconds without reaching a connected state."
            )
            details = disconnect_result.details or disconnect_result.message
            failed_session = ConnectionSession(
                id=str(uuid4()),
                profile_id=profile.id,
                status=ConnectionStatus.FAILED,
                started_at=now,
                ended_at=now,
                reconnect_count=session.reconnect_count,
                last_error=timeout_message,
            )
            latest_sessions[profile.id] = self._save_session(failed_session)
            self._append_event(
                profile.id,
                EventLevel.ERROR,
                "connection.timeout",
                f"Connection '{profile.name}' timed out while {row.status.value}.",
                details,
            )
            changed = True

        return latest_sessions, changed

    def _save_port_mapping_state(self, mapping: PortMapping) -> None:
        if self._port_mapping_repository is None:
            return
        try:
            self._port_mapping_repository.save(mapping)
        except Exception:
            LOGGER.exception("Could not persist SSH mapping state for %s", mapping.name)

    def _require_port_mapping(self, mapping_id: str) -> PortMapping:
        if self._port_mapping_repository is None:
            raise RuntimeError("SSH port mapping storage is not available.")
        mapping = self._port_mapping_repository.get_by_id(mapping_id)
        if mapping is None:
            raise ValueError(f"Unknown SSH port mapping id: {mapping_id}")
        return mapping

    def _decrypt_port_mapping_password(self, mapping: PortMapping) -> str | None:
        if not mapping.encrypted_password:
            return None
        return self._secret_manager.decrypt(mapping.encrypted_password)

    def _mapping_duration(self, mapping: PortMapping) -> str:
        if mapping.last_started_at is None:
            return "-"
        started_at = mapping.last_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = max(int((datetime.now(timezone.utc) - started_at).total_seconds()), 0)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _disconnect_runtime_profile(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.OPENVPN:
            return self._openvpn_manager.disconnect_profile(profile)
        return self._ppp_manager.disconnect(profile)

    def _require_profile(self, profile_id: str) -> ConnectionProfile:
        profile = self._profile_repository.get_by_id(profile_id)
        if profile is None:
            raise ValueError(f"Unknown profile id: {profile_id}")
        return profile

    def _safe_error(self, exc: Exception) -> str:
        detail = str(exc).strip()
        return detail or exc.__class__.__name__

    def _decrypt_password(self, profile: ConnectionProfile) -> str | None:
        if not profile.encrypted_password:
            return None
        return self._secret_manager.decrypt(profile.encrypted_password)

    def _prepare_config_payload(
        self,
        existing: ConnectionProfile | None,
        incoming: dict[str, object],
    ) -> dict[str, object]:
        payload = dict(existing.config_payload) if existing else {}
        payload.update(incoming)
        plain_ipsec_psk = str(payload.pop("ipsec_psk", "")).strip()
        if plain_ipsec_psk:
            payload["encrypted_ipsec_psk"] = self._secret_manager.encrypt(plain_ipsec_psk)
        elif existing and "encrypted_ipsec_psk" in existing.config_payload:
            payload["encrypted_ipsec_psk"] = existing.config_payload["encrypted_ipsec_psk"]
        return payload

    def _build_runtime_profile(self, profile: ConnectionProfile) -> ConnectionProfile:
        payload = dict(profile.config_payload)
        encrypted_ipsec_psk = str(payload.get("encrypted_ipsec_psk", "")).strip()
        if encrypted_ipsec_psk:
            payload["ipsec_psk"] = self._secret_manager.decrypt(encrypted_ipsec_psk)
        return ConnectionProfile(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            server_address=profile.server_address,
            protocol=profile.protocol,
            port=profile.port,
            username=profile.username,
            encrypted_password=profile.encrypted_password,
            route_metric=profile.route_metric,
            dns_servers=profile.dns_servers,
            mtu=profile.mtu,
            keepalive=profile.keepalive,
            auto_reconnect=profile.auto_reconnect,
            allow_multiple=profile.allow_multiple,
            tags=profile.tags,
            config_payload=payload,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _build_inspector_logs(self, profile: ConnectionProfile) -> list[str]:
        event_logs = self.list_logs(profile.id, limit=40)
        runtime_logs = self._openvpn_runtime_logs(profile, limit=160)
        sections: list[str] = []
        if event_logs:
            sections.extend(["=== KOPDES Events ===", *event_logs])
        if runtime_logs:
            if sections:
                sections.append("")
            sections.extend(["=== OpenVPN Runtime ===", *runtime_logs])
        if sections:
            return sections
        return ["No logs available for this connection yet."]

    def _openvpn_runtime_logs(self, profile: ConnectionProfile, limit: int) -> list[str]:
        if profile.protocol != ProtocolType.OPENVPN:
            return []
        return self._openvpn_manager.read_runtime_logs(profile, limit)

    def _import_tags(self, config_payload: dict[str, object]) -> list[str]:
        tags = ["imported", str(config_payload.get("openvpn_backend", "openvpn"))]
        if self._config_bool(config_payload.get("auth_user_pass_required")):
            tags.append("auth-user-pass")
        return tags

    def _config_bool(self, value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
