from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime, timezone

from kopdes.application.dtos.runtime_state import (
    ConnectionInspector,
    ConnectionRow,
    InterfaceSnapshot,
)
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.shared.enums import ConnectionStatus, HealthCheckType, ProtocolType


class SessionMonitor:
    def __init__(
        self,
        openvpn_manager,
        ppp_manager,
        route_manager,
        interface_monitor,
        dns_monitor,
        health_monitor,
    ) -> None:
        self._openvpn_manager = openvpn_manager
        self._ppp_manager = ppp_manager
        self._route_manager = route_manager
        self._interface_monitor = interface_monitor
        self._dns_monitor = dns_monitor
        self._health_monitor = health_monitor
        self._upload_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=24))
        self._download_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=24))

    def build_rows(
        self,
        profiles: list[ConnectionProfile],
        latest_sessions: dict[str, ConnectionSession],
    ) -> list[ConnectionRow]:
        interfaces = self._interface_monitor.collect()
        openvpn_sessions = {item.name: item for item in self._openvpn_manager.list_sessions()}
        ppp_active = self._ppp_manager.list_active_connections()
        routes = self._route_manager.list_routes()
        rows: list[ConnectionRow] = []

        for profile in profiles:
            persisted = latest_sessions.get(profile.id)
            interface = self._match_interface(profile, interfaces, openvpn_sessions, ppp_active)
            session = openvpn_sessions.get(profile.name)
            runtime_status = self._resolve_runtime_status(profile, persisted, session, interface, ppp_active)
            gateway = "-"
            if interface:
                for route in routes:
                    if route.device == interface.name and route.destination == "default":
                        gateway = route.gateway or "-"
                        break

            rx_rate = interface.rx_rate_bps if interface else 0.0
            tx_rate = interface.tx_rate_bps if interface else 0.0
            self._upload_history[profile.id].append(tx_rate)
            self._download_history[profile.id].append(rx_rate)

            rows.append(
                ConnectionRow(
                    profile_id=profile.id,
                    status=runtime_status,
                    name=profile.name,
                    protocol=profile.protocol.value,
                    server=profile.server_address,
                    backend=str(profile.config_payload.get("openvpn_backend", "system")) if profile.protocol == ProtocolType.OPENVPN else "system",
                    local_ip=interface.ipv4 if interface and interface.ipv4 else "-",
                    remote_ip=profile.server_address,
                    latency_ms=None,
                    rx_rate_bps=rx_rate,
                    tx_rate_bps=tx_rate,
                    total_rx_bytes=interface.rx_bytes if interface else 0,
                    total_tx_bytes=interface.tx_bytes if interface else 0,
                    duration_text=self._format_duration(persisted),
                    reconnect_count=persisted.reconnect_count if persisted else 0,
                    last_error=(persisted.last_error or "-") if persisted else "-",
                    interface_name=interface.name if interface else "-",
                    gateway=gateway,
                    upload_history=list(self._upload_history[profile.id]),
                    download_history=list(self._download_history[profile.id]),
                )
            )

        return rows

    def build_inspector(
        self,
        profile: ConnectionProfile,
        row: ConnectionRow,
        logs: list[str],
    ) -> ConnectionInspector:
        routes = self._route_manager.list_routes()
        rules = self._route_manager.list_rules()
        dns = self._dns_monitor.collect()
        interfaces = self._interface_monitor.collect()
        scoped_interfaces = [item for item in interfaces if item.name == row.interface_name] or interfaces
        scoped_routes = [item for item in routes if item.device == row.interface_name] or routes
        latency_ms, packet_loss = self._probe(profile.server_address, row.status)
        mtu = str(scoped_interfaces[0].mtu) if scoped_interfaces else "-"
        updated_row = ConnectionRow(
            profile_id=row.profile_id,
            status=row.status,
            name=row.name,
            protocol=row.protocol,
            server=row.server,
            backend=row.backend,
            local_ip=row.local_ip,
            remote_ip=row.remote_ip,
            latency_ms=latency_ms,
            rx_rate_bps=row.rx_rate_bps,
            tx_rate_bps=row.tx_rate_bps,
            total_rx_bytes=row.total_rx_bytes,
            total_tx_bytes=row.total_tx_bytes,
            duration_text=row.duration_text,
            reconnect_count=row.reconnect_count,
            last_error=row.last_error,
            interface_name=row.interface_name,
            gateway=row.gateway,
            packet_loss=packet_loss,
            upload_history=row.upload_history,
            download_history=row.download_history,
        )
        return ConnectionInspector(
            profile=profile,
            row=updated_row,
            dns=dns,
            routes=scoped_routes,
            rules=rules,
            interfaces=scoped_interfaces,
            tunnel_ip=row.local_ip,
            gateway=row.gateway,
            dns_display=", ".join(dns.servers) if dns.servers else "-",
            packet_loss=packet_loss,
            mtu=mtu,
            reconnect_count=row.reconnect_count,
            log_messages=logs,
            upload_history=row.upload_history,
            download_history=row.download_history,
        )

    def _match_interface(
        self,
        profile: ConnectionProfile,
        interfaces: list[InterfaceSnapshot],
        openvpn_sessions: dict[str, object],
        ppp_active: dict[str, dict[str, str]],
    ) -> InterfaceSnapshot | None:
        if profile.name in ppp_active:
            device = ppp_active[profile.name].get("device")
            for item in interfaces:
                if item.name == device:
                    return item
        session = openvpn_sessions.get(profile.name)
        if profile.protocol == ProtocolType.OPENVPN and session and getattr(session, "interface_name", None):
            session_interface = str(session.interface_name).strip()
            for item in interfaces:
                if item.name == session_interface:
                    return item
            if session_interface in {"tun", "tap", "ppp"}:
                for item in interfaces:
                    if item.name.startswith(session_interface) and item.is_up:
                        return item
        explicit = str(profile.config_payload.get("interface_name", "")).strip()
        if explicit and profile.protocol != ProtocolType.OPENVPN:
            for item in interfaces:
                if item.name == explicit:
                    return item
        if profile.protocol != ProtocolType.OPENVPN:
            for item in interfaces:
                if item.kind == "ppp":
                    return item
        return None

    def _resolve_runtime_status(
        self,
        profile: ConnectionProfile,
        persisted: ConnectionSession | None,
        session,
        interface: InterfaceSnapshot | None,
        ppp_active: dict[str, dict[str, str]],
    ) -> ConnectionStatus:
        if profile.protocol == ProtocolType.OPENVPN:
            if session:
                session_status = self._resolve_openvpn_session_status(session.status_text, persisted)
                if interface and interface.kind in {"tun", "tap"} and interface.is_up and interface.ipv4:
                    if session_status in {ConnectionStatus.FAILED, ConnectionStatus.RECONNECTING}:
                        return session_status
                    return ConnectionStatus.ACTIVE
                if session_status != ConnectionStatus.ACTIVE:
                    return session_status
                return ConnectionStatus.CONNECTING
            if interface and interface.kind in {"tun", "tap"} and interface.is_up and interface.ipv4:
                return ConnectionStatus.DEGRADED
        elif profile.name in ppp_active:
            return ConnectionStatus.ACTIVE
        if persisted:
            if persisted.status == ConnectionStatus.DISCONNECTING:
                return ConnectionStatus.INACTIVE
            return persisted.status
        return ConnectionStatus.INACTIVE

    def _resolve_openvpn_session_status(
        self,
        status_text: str,
        persisted: ConnectionSession | None,
    ) -> ConnectionStatus:
        normalized = status_text.strip().lower()
        if any(token in normalized for token in ("connected", "success", "initialization sequence completed")):
            return ConnectionStatus.ACTIVE
        if any(token in normalized for token in ("auth_failed", "failed", "fatal", "error", "exiting")):
            return ConnectionStatus.FAILED
        if "reconnect" in normalized:
            return ConnectionStatus.RECONNECTING
        if any(token in normalized for token in ("connecting", "running", "resolv", "wait", "tls", "handshake", "auth", "route")):
            if persisted and persisted.status == ConnectionStatus.RECONNECTING:
                return ConnectionStatus.RECONNECTING
            return ConnectionStatus.CONNECTING
        return ConnectionStatus.DEGRADED

    def _probe(self, host: str, status: ConnectionStatus) -> tuple[float | None, str]:
        if status not in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}:
            return None, "-"
        result = self._health_monitor.run(HealthCheckType.PING, host, timeout=2)
        packet_loss = "-"
        if result.detail:
            match = re.search(r"(\d+(?:\.\d+)?)%\s+packet loss", result.detail)
            if match:
                packet_loss = f"{match.group(1)}%"
        return result.latency_ms, packet_loss

    def _format_duration(self, session: ConnectionSession | None) -> str:
        if session is None or session.started_at is None:
            return "-"
        started = session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - started
        seconds = int(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
