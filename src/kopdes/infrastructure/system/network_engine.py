from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.infrastructure.system.command_runner import CommandRunner
from kopdes.shared.enums import ConnectionStatus, ProtocolType


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EngineActionPlan:
    command: list[str]
    requires_privilege: bool = True


class ProtocolHandler:
    def validate(self, profile: ConnectionProfile) -> None:
        if not profile.server_address:
            raise ValueError("Server address is required.")

    def build_connect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        raise NotImplementedError

    def build_disconnect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        raise NotImplementedError


class OpenVpnHandler(ProtocolHandler):
    def build_connect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        return EngineActionPlan(
            command=["openvpn", "--config", f"/etc/openvpn/{profile.name}.ovpn"],
        )

    def build_disconnect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        return EngineActionPlan(command=["pkill", "-f", profile.name])


class PppHandler(ProtocolHandler):
    def build_connect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        return EngineActionPlan(command=["pon", profile.name])

    def build_disconnect_plan(self, profile: ConnectionProfile) -> EngineActionPlan:
        return EngineActionPlan(command=["poff", profile.name])


class NetworkEngine:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner
        self._handlers: dict[ProtocolType, ProtocolHandler] = {
            ProtocolType.OPENVPN: OpenVpnHandler(),
            ProtocolType.PPP: PppHandler(),
            ProtocolType.PPTP: PppHandler(),
            ProtocolType.L2TP: PppHandler(),
            ProtocolType.L2TP_IPSEC: PppHandler(),
            ProtocolType.PPPOE: PppHandler(),
        }

    def connect(self, profile: ConnectionProfile) -> ConnectionSession:
        handler = self._get_handler(profile.protocol)
        handler.validate(profile)
        plan = handler.build_connect_plan(profile)
        LOGGER.info("Prepared connect plan for %s: %s", profile.name, plan.command)
        return ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.CONNECTING,
            started_at=datetime.utcnow(),
            last_error=None,
        )

    def disconnect(self, profile: ConnectionProfile) -> ConnectionSession:
        handler = self._get_handler(profile.protocol)
        plan = handler.build_disconnect_plan(profile)
        LOGGER.info("Prepared disconnect plan for %s: %s", profile.name, plan.command)
        return ConnectionSession(
            id=str(uuid4()),
            profile_id=profile.id,
            status=ConnectionStatus.DISCONNECTING,
            started_at=datetime.utcnow(),
            last_error=None,
        )

    def _get_handler(self, protocol: ProtocolType) -> ProtocolHandler:
        handler = self._handlers.get(protocol)
        if handler is None:
            raise NotImplementedError(f"Unsupported protocol handler: {protocol.value}")
        return handler
