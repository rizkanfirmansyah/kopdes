from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from kopdes.application.dtos.connection_profile_dto import (
    ConnectionProfileInput,
    DashboardStats,
)
from kopdes.application.dtos.runtime_state import ActionResult, ConnectionInspector, ConnectionRow
from kopdes.application.ports.repositories import (
    ConnectionProfileRepository,
    ConnectionSessionRepository,
    EventLogRepository,
)
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.domain.entities.event_log import EventLog
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.infrastructure.system.config_parser import ConfigImportParser
from kopdes.infrastructure.system.system_metrics import SystemMetricsCollector
from kopdes.shared.enums import ConnectionStatus, EventLevel, ProtocolType


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

    def get_dashboard_stats(self) -> DashboardStats:
        rows = self.list_connection_rows()
        metrics = self._metrics_collector.collect()
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
        profiles = self._profile_repository.list_all()
        latest_sessions = self._latest_sessions_by_profile()
        rows = self._session_monitor.build_rows(profiles, latest_sessions)
        latest_sessions, changed = self._expire_stale_pending_sessions(profiles, latest_sessions, rows)
        if changed:
            rows = self._session_monitor.build_rows(profiles, latest_sessions)
        return rows

    def get_profile(self, profile_id: str) -> ConnectionProfile | None:
        return self._profile_repository.get_by_id(profile_id)

    def save_profile(
        self,
        data: ConnectionProfileInput,
        profile_id: str | None = None,
    ) -> ConnectionProfile:
        existing = self._profile_repository.get_by_id(profile_id) if profile_id else None
        encrypted_password = existing.encrypted_password if existing else None
        if data.password:
            encrypted_password = self._secret_manager.encrypt(data.password)
        config_payload = self._prepare_config_payload(existing, data.config_payload)
        if data.protocol == ProtocolType.OPENVPN:
            config_payload.setdefault("openvpn_backend", str(config_payload.get("openvpn_backend", "openvpn")))
        profile = ConnectionProfile(
            id=existing.id if existing else str(uuid4()),
            name=data.name,
            description=data.description,
            server_address=data.server_address,
            protocol=data.protocol,
            port=data.port,
            username=data.username,
            encrypted_password=encrypted_password,
            route_metric=data.route_metric,
            dns_servers=data.dns_servers,
            mtu=data.mtu,
            keepalive=data.keepalive,
            auto_reconnect=data.auto_reconnect,
            allow_multiple=data.allow_multiple,
            tags=data.tags,
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
        runtime_profile = self._build_runtime_profile(profile)
        password = self._decrypt_password(profile)
        if profile.protocol == ProtocolType.OPENVPN:
            result = self._openvpn_manager.start_session(runtime_profile, password)
        else:
            result = self._ppp_manager.connect(runtime_profile, password)
        latest = self._latest_sessions_by_profile().get(profile.id)
        session = ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.CONNECTING if result.success else ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            reconnect_count=latest.reconnect_count if latest else 0,
            last_error=None if result.success else (result.details or result.message),
        )
        self._session_repository.save(session)
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
        if profile.protocol == ProtocolType.OPENVPN:
            result = self._openvpn_manager.disconnect_profile(profile)
        else:
            result = self._ppp_manager.disconnect(profile)
        session = ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.DISCONNECTING if result.success else ConnectionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            last_error=None if result.success else (result.details or result.message),
        )
        self._session_repository.save(session)
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
        self._session_repository.save(session)
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
        events = self._event_repository.list_recent(limit)
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

            disconnect_result = self._disconnect_runtime_profile(profile)
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
            latest_sessions[profile.id] = self._session_repository.save(failed_session)
            self._append_event(
                profile.id,
                EventLevel.ERROR,
                "connection.timeout",
                f"Connection '{profile.name}' timed out while {row.status.value}.",
                details,
            )
            changed = True

        return latest_sessions, changed

    def _disconnect_runtime_profile(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.OPENVPN:
            return self._openvpn_manager.disconnect_profile(profile)
        return self._ppp_manager.disconnect(profile)

    def _require_profile(self, profile_id: str) -> ConnectionProfile:
        profile = self._profile_repository.get_by_id(profile_id)
        if profile is None:
            raise ValueError(f"Unknown profile id: {profile_id}")
        return profile

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
