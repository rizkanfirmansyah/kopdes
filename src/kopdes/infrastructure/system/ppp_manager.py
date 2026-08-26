from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterable

from kopdes.application.dtos.runtime_state import ActionResult
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandRunner, CommandResult
from kopdes.shared.enums import ProtocolType


LOGGER = logging.getLogger(__name__)
_MANAGED_PROTOCOLS = {
    ProtocolType.PPP,
    ProtocolType.PPPOE,
    ProtocolType.PPTP,
    ProtocolType.L2TP,
    ProtocolType.L2TP_IPSEC,
}


class PppManager:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def list_active_connections(self) -> dict[str, dict[str, str]]:
        if shutil.which("nmcli") is None:
            return {}
        result = self._command_runner.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"],
            timeout=20,
        )
        if result.return_code != 0:
            return {}
        active: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 3:
                continue
            active[parts[0]] = {"type": parts[1], "device": parts[2]}
        return active

    def connect(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            return self._connect_generic_ppp(profile, password)
        if profile.protocol not in _MANAGED_PROTOCOLS:
            return ActionResult(False, f"Unsupported PPP protocol: {profile.protocol.value}.")
        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        return self._connect_nmcli(profile, password)

    def disconnect(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            peer = self._peer_name(profile)
            result = self._run_privileged(["poff", peer], timeout=30)
            if result.return_code != 0 and not self._is_already_stopped(result):
                return ActionResult(False, "PPP disconnect failed.", self._result_detail(result))
            return ActionResult(True, f"Disconnected PPP peer '{peer}'.", self._result_detail(result))

        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        result = self._run_privileged(
            ["nmcli", "connection", "down", "id", profile.name],
            timeout=45,
        )
        if result.return_code != 0 and not self._is_already_stopped(result):
            return ActionResult(False, "Connection disconnect failed.", self._result_detail(result))
        return ActionResult(True, f"Disconnected '{profile.name}'.", self._result_detail(result))

    def delete(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            return ActionResult(
                True,
                "PPP profile deleted from KOPDES.",
                "System peer files were preserved; remove them separately if they are no longer needed.",
            )
        if shutil.which("nmcli") is None:
            return ActionResult(
                True,
                "Profile removed from KOPDES.",
                "nmcli is not installed, so no system connection was removed.",
            )
        result = self._run_privileged(
            ["nmcli", "connection", "delete", "id", profile.name],
            timeout=45,
        )
        if result.return_code != 0 and not self._is_already_stopped(result):
            return ActionResult(False, "Failed to delete nmcli connection.", self._result_detail(result))
        return ActionResult(True, f"Deleted system connection '{profile.name}'.", self._result_detail(result))

    def shutdown(self, profiles: Iterable[ConnectionProfile]) -> ActionResult:
        """Stop only PPP/NM connections owned by profiles stored in KOPDES."""
        active = self.list_active_connections()
        failures: list[str] = []
        stopped = 0
        for profile in profiles:
            if profile.protocol not in _MANAGED_PROTOCOLS:
                continue
            if profile.protocol != ProtocolType.PPP and profile.name not in active:
                continue
            result = self.disconnect(profile)
            if result.success:
                stopped += 1
            else:
                failures.append(f"{profile.name}: {result.message}")
        if failures:
            return ActionResult(False, "Some PPP connections could not be stopped.", "\n".join(failures))
        return ActionResult(True, f"Stopped {stopped} managed PPP connection(s).")

    def _connect_generic_ppp(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if shutil.which("pppd") is None:
            return ActionResult(False, "pppd is not installed on this system.")
        peer = self._peer_name(profile)
        command = ["pppd", "call", peer]
        if profile.username:
            command.extend(["user", profile.username])
        if password:
            command.extend(["password", password])
        result = self._run_privileged(command, timeout=45)
        if result.return_code != 0:
            return ActionResult(False, "PPP connection failed.", self._result_detail(result))
        return ActionResult(True, f"Started PPP peer '{peer}'.", self._result_detail(result))

    def _connect_nmcli(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        create = self._ensure_nmcli_profile(profile, password)
        if not create.success:
            return create
        result = self._run_privileged(
            ["nmcli", "connection", "up", "id", profile.name],
            timeout=60,
        )
        if result.return_code != 0:
            plugin_error = self._missing_vpn_plugin(profile.protocol, self._result_detail(result))
            if plugin_error is not None:
                return plugin_error
            return ActionResult(False, "Connection startup failed.", self._result_detail(result))
        return ActionResult(True, f"Connected '{profile.name}'.", self._result_detail(result))

    def _ensure_nmcli_profile(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if profile.protocol == ProtocolType.PPPOE:
            ifname = str(profile.config_payload.get("interface_name", "eth0")).strip() or "eth0"
            command = [
                "nmcli",
                "connection",
                "add",
                "type",
                "pppoe",
                "ifname",
                ifname,
                "con-name",
                profile.name,
                "username",
                profile.username or "",
                "password",
                password or "",
                "connection.autoconnect",
                "no",
            ]
        else:
            vpn_type = "l2tp" if profile.protocol in {ProtocolType.L2TP, ProtocolType.L2TP_IPSEC} else "pptp"
            vpn_data = [f"gateway={profile.server_address}"]
            if profile.username:
                vpn_data.append(f"user={profile.username}")
            if profile.protocol == ProtocolType.L2TP_IPSEC:
                vpn_data.append("ipsec-enabled=yes")
            secrets: list[str] = []
            if password:
                secrets.append(f"password={password}")
            ipsec_psk = str(profile.config_payload.get("ipsec_psk", "")).strip()
            if ipsec_psk:
                secrets.append(f"ipsec-psk={ipsec_psk}")
            command = [
                "nmcli",
                "connection",
                "add",
                "type",
                "vpn",
                "con-name",
                profile.name,
                "ifname",
                "*",
                "vpn-type",
                vpn_type,
                "vpn.data",
                ",".join(vpn_data),
                "vpn.secrets",
                ",".join(secrets),
                "connection.autoconnect",
                "no",
            ]

        result = self._run_privileged(command, timeout=45)
        if result.return_code == 0:
            return ActionResult(True, f"Prepared system profile '{profile.name}'.", self._result_detail(result))
        detail = self._result_detail(result)
        plugin_error = self._missing_vpn_plugin(profile.protocol, detail)
        if plugin_error is not None:
            return plugin_error
        if "already exists" in detail.lower():
            # Existing profiles are kept, but autoconnect is disabled so KOPDES owns shutdown.
            modify = self._run_privileged(
                ["nmcli", "connection", "modify", "id", profile.name, "connection.autoconnect", "no"],
                timeout=30,
            )
            if modify.return_code == 0:
                return ActionResult(True, f"Reused system profile '{profile.name}'.", self._result_detail(modify))
            return ActionResult(False, "Failed to update the existing nmcli profile.", self._result_detail(modify))
        return ActionResult(False, "Failed to create nmcli profile.", self._result_detail(result))

    def _missing_vpn_plugin(
        self,
        protocol: ProtocolType,
        detail: str,
    ) -> ActionResult | None:
        normalized = detail.lower()
        if "not installed" not in normalized and "was not installed" not in normalized:
            return None
        plugin: str | None = None
        if protocol in {ProtocolType.L2TP, ProtocolType.L2TP_IPSEC} and "networkmanager.l2tp" in normalized:
            plugin = "network-manager-l2tp"
        elif protocol == ProtocolType.PPTP and "networkmanager.pptp" in normalized:
            plugin = "network-manager-pptp"
        elif protocol == ProtocolType.OPENVPN and "networkmanager.openvpn" in normalized:
            plugin = "network-manager-openvpn"
        if plugin is None:
            return None
        return ActionResult(
            False,
            f"NetworkManager {protocol.value.upper()} plugin is not installed.",
            f"Install '{plugin}', then retry the connection. On Ubuntu/Debian: "
            f"sudo apt-get install {plugin}.",
        )

    def _run_privileged(self, command: list[str], timeout: int) -> CommandResult:
        runner = getattr(self._command_runner, "run_privileged", None)
        if runner is None:
            return self._command_runner.run(command, timeout=timeout)
        try:
            return runner(command, timeout=timeout, interactive=True)
        except TypeError:
            return runner(command, timeout=timeout)

    def _peer_name(self, profile: ConnectionProfile) -> str:
        peer = str(profile.config_payload.get("peer_name", profile.name)).strip()
        return peer or profile.name

    def _result_detail(self, result: CommandResult) -> str:
        return result.stderr.strip() or result.stdout.strip()

    def _is_already_stopped(self, result: CommandResult) -> bool:
        text = self._result_detail(result).lower()
        return any(
            marker in text
            for marker in (
                "not active",
                "no active",
                "not running",
                "no pppd",
                "unknown connection",
                "not found",
                "does not exist",
            )
        )
