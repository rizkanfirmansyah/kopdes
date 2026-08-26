from __future__ import annotations

import shutil

from kopdes.application.dtos.runtime_state import ActionResult
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandRunner
from kopdes.shared.enums import ProtocolType


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
        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        return self._connect_nmcli(profile, password)

    def disconnect(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            peer = profile.config_payload.get("peer_name", profile.name)
            result = self._command_runner.run(["poff", str(peer)], timeout=30)
            if result.return_code != 0:
                return ActionResult(False, "PPP disconnect failed.", result.stderr.strip())
            return ActionResult(True, f"Disconnected PPP peer '{peer}'.", result.stdout.strip())

        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        result = self._command_runner.run(
            ["nmcli", "connection", "down", "id", profile.name],
            timeout=45,
        )
        if result.return_code != 0:
            return ActionResult(False, "Connection disconnect failed.", result.stderr.strip())
        return ActionResult(True, f"Disconnected '{profile.name}'.", result.stdout.strip())

    def delete(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            return ActionResult(True, "PPP profile deleted from KOPDES. System peer files were not removed.")
        if shutil.which("nmcli") is None:
            return ActionResult(True, "Profile removed from KOPDES. nmcli is not installed for system cleanup.")
        result = self._command_runner.run(
            ["nmcli", "connection", "delete", "id", profile.name],
            timeout=45,
        )
        if result.return_code != 0:
            return ActionResult(False, "Failed to delete nmcli connection.", result.stderr.strip())
        return ActionResult(True, f"Deleted system connection '{profile.name}'.", result.stdout.strip())

    def _connect_generic_ppp(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if shutil.which("pppd") is None:
            return ActionResult(False, "pppd is not installed on this system.")
        peer = str(profile.config_payload.get("peer_name", profile.name))
        command = ["pppd", "call", peer]
        if profile.username:
            command.extend(["user", profile.username])
        if password:
            command.extend(["password", password])
        result = self._command_runner.run(command, timeout=45)
        if result.return_code != 0:
            return ActionResult(False, "PPP connection failed.", result.stderr.strip())
        return ActionResult(True, f"Started PPP peer '{peer}'.", result.stdout.strip())

    def _connect_nmcli(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        create = self._ensure_nmcli_profile(profile, password)
        if not create.success:
            return create
        result = self._command_runner.run(
            ["nmcli", "connection", "up", "id", profile.name],
            timeout=60,
        )
        if result.return_code != 0:
            return ActionResult(False, "Connection startup failed.", result.stderr.strip())
        return ActionResult(True, f"Connected '{profile.name}'.", result.stdout.strip())

    def _ensure_nmcli_profile(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if profile.protocol == ProtocolType.PPPOE:
            ifname = str(profile.config_payload.get("interface_name", "eth0"))
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
            ]
        else:
            vpn_type = "l2tp" if profile.protocol in {ProtocolType.L2TP, ProtocolType.L2TP_IPSEC} else "pptp"
            vpn_data = [f"gateway={profile.server_address}"]
            if profile.username:
                vpn_data.append(f"user={profile.username}")
            if profile.protocol == ProtocolType.L2TP_IPSEC:
                vpn_data.append("ipsec-enabled=yes")
            secrets = []
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
            ]

        result = self._command_runner.run(command, timeout=45)
        if result.return_code == 0 or "already exists" in result.stderr.lower():
            return ActionResult(True, f"Prepared system profile '{profile.name}'.", result.stdout.strip())
        return ActionResult(False, "Failed to create nmcli profile.", result.stderr.strip())
