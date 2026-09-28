from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import tempfile
import time
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from threading import RLock

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

def _manager_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class PppManager:
    """Manage NetworkManager PPP links and owned generic pppd processes."""

    STARTUP_TIMEOUT_SECONDS = 5.0
    STOP_TIMEOUT_SECONDS = 5.0

    def __init__(self, command_runner: CommandRunner, data_dir: Path | None = None) -> None:
        self._command_runner = command_runner
        base_dir = Path(data_dir).expanduser() if data_dir is not None else Path.home() / ".local" / "state" / "kopdes"
        self._runtime_dir = base_dir / "ppp" / "runtime"
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._runtime_dir, 0o700)
        self._lock = RLock()

    @_manager_locked
    def list_active_connections(self) -> dict[str, dict[str, str]]:
        active = self._owned_ppp_connections()
        if shutil.which("nmcli") is None:
            return active
        result = self._command_runner.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"],
            timeout=20,
        )
        if result.return_code != 0:
            return active
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            active.setdefault(parts[0], {"type": parts[1], "device": parts[2]})
        return active

    @_manager_locked
    def connect(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            return self._connect_generic_ppp(profile, password)
        if profile.protocol not in _MANAGED_PROTOCOLS:
            return ActionResult(False, f"Unsupported PPP protocol: {profile.protocol.value}.")
        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        return self._connect_nmcli(profile, password)

    @_manager_locked
    def disconnect(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            return self._disconnect_generic_ppp(profile)

        if shutil.which("nmcli") is None:
            return ActionResult(False, "nmcli is not installed on this system.")
        result = self._run_privileged(
            ["nmcli", "connection", "down", "id", profile.name],
            timeout=45,
        )
        if result.return_code != 0 and not self._is_already_stopped(result):
            return ActionResult(False, "Connection disconnect failed.", self._result_detail(result))
        return ActionResult(True, f"Disconnected '{profile.name}'.", self._result_detail(result))

    @_manager_locked
    def delete(self, profile: ConnectionProfile) -> ActionResult:
        if profile.protocol == ProtocolType.PPP:
            stopped = self._disconnect_generic_ppp(profile)
            if not stopped.success:
                return stopped
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

    @_manager_locked
    def shutdown(self, profiles: Iterable[ConnectionProfile]) -> ActionResult:
        """Stop only NetworkManager links and pppd processes owned by KOPDES."""
        active = self.list_active_connections()
        failures: list[str] = []
        stopped = 0
        for profile in profiles:
            if profile.protocol not in _MANAGED_PROTOCOLS:
                continue
            if profile.protocol == ProtocolType.PPP:
                metadata = self._read_metadata(profile.id)
                pid = self._as_pid(metadata.get("pid")) if metadata else None
                if metadata is None or pid is None or not self._pid_matches(pid, metadata):
                    continue
            elif profile.name not in active:
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
        if not self._valid_peer(peer):
            return ActionResult(
                False,
                "PPP peer name is invalid.",
                "Use only letters, numbers, dots, underscores, and hyphens in the peer name.",
            )
        secret_error = self._validate_secret(password)
        if secret_error:
            return ActionResult(False, "PPP credentials are invalid.", secret_error)

        existing = self._read_metadata(profile.id)
        if existing:
            existing_pid = self._as_pid(existing.get("pid"))
            if existing_pid and self._pid_matches(existing_pid, existing):
                return ActionResult(
                    False,
                    f"PPP peer '{peer}' is already running.",
                    f"Managed PID: {existing_pid}. Disconnect it before starting another session.",
                )
            if existing_pid and self._pid_exists(existing_pid):
                return ActionResult(
                    False,
                    "An existing PPP process could not be verified as KOPDES-owned.",
                    f"PID {existing_pid} was left untouched for safety.",
                )
            self._remove_metadata(existing)

        link_name = self._link_name(profile)
        options_path: Path | None = None
        command = ["pppd", "call", peer, "linkname", link_name]
        try:
            if profile.username or password:
                options_path = self._create_pppd_options(profile.username, password)
                command.extend(["file", str(options_path)])
            result = self._run_privileged(command, timeout=45, redact_values=[password])
            detail = self._result_detail(result, [password])
            if result.return_code != 0:
                self._cleanup_start_candidate(link_name, peer)
                return ActionResult(False, "PPP connection failed.", detail)

            pid_record = self._wait_for_pid(link_name)
            if pid_record is None:
                self._cleanup_start_candidate(link_name, peer)
                return ActionResult(
                    False,
                    "PPP did not publish an ownership PID.",
                    "KOPDES stopped waiting without terminating an unverified process.",
                )
            pid, pid_path = pid_record
            metadata = {
                "profile_id": profile.id,
                "name": profile.name,
                "protocol": profile.protocol.value,
                "peer": peer,
                "linkname": link_name,
                "pid": pid,
                "pid_path": str(pid_path),
                "pid_start_time": self._process_start_time(pid),
                "started_at": time.time(),
                "state": "STARTING",
                "exit_code": None,
                "last_error": "",
                "interface_name": str(profile.config_payload.get("interface_name", "")).strip(),
            }
            if not metadata["pid_start_time"] or not self._pid_matches(pid, metadata):
                self._cleanup_start_candidate(link_name, peer)
                return ActionResult(
                    False,
                    "PPP process ownership could not be verified.",
                    f"PID {pid} was not registered because its start time or command identity did not match.",
                )
            try:
                self._write_metadata(profile.id, metadata)
            except OSError as exc:
                self._terminate_owned_pid(pid, metadata)
                self._remove_pid_file(link_name, pid_path)
                return ActionResult(False, "PPP session metadata could not be saved.", str(exc))
            metadata["state"] = "RUNNING"
            self._write_metadata_best_effort(profile.id, metadata)
            return ActionResult(
                True,
                f"Started PPP peer '{peer}'.",
                detail,
                {"pid": str(pid), "runtime_path": str(self._metadata_path(profile.id))},
            )
        finally:
            if options_path is not None:
                try:
                    options_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not remove temporary PPP options file %s", options_path)

    def _disconnect_generic_ppp(self, profile: ConnectionProfile) -> ActionResult:
        metadata = self._read_metadata(profile.id)
        peer = self._peer_name(profile)
        if not metadata:
            return ActionResult(
                True,
                f"PPP peer '{peer}' is not managed by KOPDES.",
                "No owned PID metadata was found; no unowned PPP process was terminated.",
            )
        pid = self._as_pid(metadata.get("pid"))
        if pid is None or not self._pid_exists(pid):
            self._remove_metadata(metadata)
            return ActionResult(True, f"PPP peer '{peer}' was already stopped.")
        if not self._pid_matches(pid, metadata):
            self._mark_metadata_failed(
                profile.id,
                metadata,
                "PPP PID ownership validation failed; the process was left untouched.",
            )
            return ActionResult(
                False,
                "PPP disconnect refused because process ownership could not be verified.",
                f"PID {pid} was left untouched for safety.",
            )

        metadata["state"] = "STOPPING"
        self._write_metadata_best_effort(profile.id, metadata)
        if not self._terminate_owned_pid(pid, metadata):
            self._mark_metadata_failed(profile.id, metadata, f"Managed PPP PID {pid} did not stop.")
            return ActionResult(False, "PPP disconnect failed.", f"Managed PID {pid} is still running.")
        self._remove_pid_file(str(metadata.get("linkname", "")), Path(str(metadata.get("pid_path", ""))))
        self._remove_metadata(metadata)
        return ActionResult(True, f"Disconnected PPP peer '{peer}'.")

    def _connect_nmcli(self, profile: ConnectionProfile, password: str | None) -> ActionResult:
        ipsec_psk = str(profile.config_payload.get("ipsec_psk", "")).strip()
        secret_values = [password, ipsec_psk]
        secret_error = next((self._validate_secret(value) for value in secret_values if value), None)
        if secret_error:
            return ActionResult(False, "Connection credentials are invalid.", secret_error)
        secret_path: Path | None = None
        try:
            create = self._ensure_nmcli_profile(profile)
            if not create.success:
                return create
            persisted = self._persist_nmcli_secrets(profile, password, ipsec_psk)
            if not persisted.success:
                return persisted
            secret_path = self._create_nmcli_passwd_file(profile, password, ipsec_psk)
            command = ["nmcli", "connection", "up", "id", profile.name]
            if secret_path is not None:
                command.extend(["passwd-file", str(secret_path)])
            result = self._run_privileged(command, timeout=60, redact_values=secret_values)
            if result.return_code != 0:
                plugin_error = self._missing_vpn_plugin(profile.protocol, self._result_detail(result, secret_values))
                if plugin_error is not None:
                    return plugin_error
                return ActionResult(False, "Connection startup failed.", self._result_detail(result, secret_values))
            return ActionResult(True, f"Connected '{profile.name}'.", self._result_detail(result, secret_values))
        finally:
            if secret_path is not None:
                try:
                    secret_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not remove temporary NetworkManager password file %s", secret_path)

    def _ensure_nmcli_profile(self, profile: ConnectionProfile, password: str | None = None) -> ActionResult:
        del password
        self._delete_stale_nmcli_connections(profile.name)
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
                vpn_data.append("ipsec-psk-flags=0")
            vpn_data.append("password-flags=0")
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
            modify = self._run_privileged(
                ["nmcli", "connection", "modify", "id", profile.name, "connection.autoconnect", "no"],
                timeout=30,
            )
            if modify.return_code == 0:
                return ActionResult(True, f"Reused system profile '{profile.name}'.", self._result_detail(modify))
            return ActionResult(False, "Failed to update the existing nmcli profile.", self._result_detail(modify))
        return ActionResult(False, "Failed to create nmcli profile.", detail)

    def _persist_nmcli_secrets(
        self,
        profile: ConnectionProfile,
        password: str | None,
        ipsec_psk: str,
    ) -> ActionResult:
        """Store secrets in the system connection (flags=0) via stdin so the VPN plugin sees them without an agent.

        network-manager-l2tp does not honor 'nmcli connection up ... passwd-file' for its secrets; it only reads
        them from the connection itself. Secrets are piped over stdin to 'nmcli connection edit', never argv.
        """
        if profile.protocol == ProtocolType.PPPOE:
            if not password:
                return ActionResult(True, "No secrets to persist.")
            script = f"set pppoe.password {password}\nsave\nquit\n"
            redact = [password]
        else:
            parts = []
            if password:
                parts.append(f"password={password}")
            if ipsec_psk:
                parts.append(f"ipsec-psk={ipsec_psk}")
            if not parts:
                return ActionResult(True, "No secrets to persist.")
            script = f"set vpn.secrets {', '.join(parts)}\nsave\nquit\n"
            redact = [password, ipsec_psk]
        result = self._run_privileged(
            ["nmcli", "connection", "edit", "id", profile.name],
            timeout=30,
            redact_values=redact,
            stdin_data=script,
        )
        if result.return_code != 0 or "error" in result.stdout.lower():
            return ActionResult(
                False,
                "Failed to store connection secrets.",
                self._result_detail(result, redact),
            )
        return ActionResult(True, "Secrets stored.")

    def _delete_stale_nmcli_connections(self, name: str) -> None:
        """Remove prior nmcli connections with this name so 'up id NAME' cannot resolve to a stale duplicate."""
        listing = self._run_privileged(["nmcli", "-t", "-f", "NAME,UUID", "connection", "show"], timeout=20)
        if listing.return_code != 0:
            return
        for line in listing.stdout.splitlines():
            con_name, _, uuid = line.partition(":")
            if con_name == name and uuid:
                self._run_privileged(["nmcli", "connection", "delete", "uuid", uuid], timeout=30)

    def _create_pppd_options(self, username: str | None, password: str | None) -> Path:
        lines: list[str] = []
        if username:
            lines.append(f"user {shlex.quote(username)}")
        if password:
            lines.append(f"password {shlex.quote(password)}")
        return self._write_private_file("\n".join(lines) + "\n", ".pppd-options-")

    def _create_nmcli_passwd_file(
        self,
        profile: ConnectionProfile,
        password: str | None,
        ipsec_psk: str,
    ) -> Path | None:
        entries: list[str] = []
        if password:
            key = "pppoe.password" if profile.protocol == ProtocolType.PPPOE else "vpn.secrets.password"
            entries.append(f"{key}:{password}")
        if ipsec_psk:
            entries.append(f"vpn.secrets.ipsec-psk:{ipsec_psk}")
        if not entries:
            return None
        return self._write_private_file("\n".join(entries) + "\n", ".nmcli-passwd-")

    def _write_private_file(self, contents: str, prefix: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=self._runtime_dir)
        path = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            return path
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _cleanup_start_candidate(self, link_name: str, peer: str) -> None:
        record = self._read_pid_record(link_name)
        if record is None:
            return
        pid, pid_path = record
        metadata = {
            "profile_id": "",
            "name": "",
            "protocol": ProtocolType.PPP.value,
            "peer": peer,
            "linkname": link_name,
            "pid": pid,
            "pid_path": str(pid_path),
            "pid_start_time": self._process_start_time(pid),
            "started_at": time.time(),
            "state": "STOPPING",
            "exit_code": None,
            "last_error": "",
        }
        if metadata["pid_start_time"] and self._pid_matches(pid, metadata):
            if self._terminate_owned_pid(pid, metadata):
                self._remove_pid_file(link_name, pid_path)

    def _wait_for_pid(self, link_name: str) -> tuple[int, Path] | None:
        deadline = time.monotonic() + self.STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            record = self._read_pid_record(link_name)
            if record is not None:
                return record
            time.sleep(0.1)
        return None

    def _read_pid_record(self, link_name: str) -> tuple[int, Path] | None:
        for path in self._pid_paths(link_name):
            try:
                pid = self._as_pid(path.read_text(encoding="ascii").strip())
            except (OSError, UnicodeError):
                continue
            if pid is not None:
                return pid, path
        return None

    def _terminate_owned_pid(self, pid: int, metadata: dict[str, object]) -> bool:
        if not self._pid_matches(pid, metadata):
            return not self._pid_exists(pid)

        def send(signum: signal.Signals, name: str) -> bool:
            if not self._pid_matches(pid, metadata):
                return True
            try:
                pgid = os.getpgid(pid)
                if pgid == pid:
                    os.killpg(pgid, signum)
                else:
                    os.kill(pid, signum)
                return True
            except ProcessLookupError:
                return True
            except PermissionError:
                result = self._run_privileged(
                    ["kill", f"-{name}", str(pid)],
                    timeout=20,
                    redact_values=(),
                )
                return result.return_code == 0
            except OSError:
                return False

        if not send(signal.SIGTERM, "TERM"):
            return False
        deadline = time.monotonic() + self.STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_exists(pid) or not self._pid_matches(pid, metadata):
                return True
            time.sleep(0.1)
        if not send(signal.SIGKILL, "KILL"):
            return False
        deadline = time.monotonic() + self.STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_exists(pid) or not self._pid_matches(pid, metadata):
                return True
            time.sleep(0.1)
        return not self._pid_exists(pid) or not self._pid_matches(pid, metadata)

    def _owned_ppp_connections(self) -> dict[str, dict[str, str]]:
        active: dict[str, dict[str, str]] = {}
        for metadata_path in sorted(self._runtime_dir.glob("*.json")):
            metadata = self._read_json(metadata_path)
            if not metadata:
                continue
            profile_name = str(metadata.get("name", "")).strip()
            pid = self._as_pid(metadata.get("pid"))
            if not profile_name or pid is None:
                continue
            if self._pid_matches(pid, metadata):
                if metadata.get("state") != "RUNNING":
                    metadata["state"] = "RUNNING"
                    metadata["last_error"] = ""
                    self._write_metadata_best_effort(str(metadata.get("profile_id", "")), metadata)
                active[profile_name] = {
                    "type": ProtocolType.PPP.value,
                    "device": str(metadata.get("interface_name", "")).strip() or "ppp",
                }
                continue
            if metadata.get("state") != "STOPPED":
                metadata["state"] = "FAILED"
                metadata["last_error"] = (
                    "PPP process exited or ownership validation failed; no process was terminated."
                )
                self._write_metadata_path_best_effort(metadata_path, metadata)
        return active

    def _mark_metadata_failed(self, profile_id: str, metadata: dict[str, object], message: str) -> None:
        metadata["state"] = "FAILED"
        metadata["last_error"] = message
        self._write_metadata_best_effort(profile_id, metadata)

    def _write_metadata_best_effort(self, profile_id: str, metadata: dict[str, object]) -> None:
        if not profile_id:
            return
        try:
            self._write_metadata(profile_id, metadata)
        except OSError:
            LOGGER.warning("Could not persist PPP runtime state for profile %s", profile_id)

    def _write_metadata_path_best_effort(self, path: Path, metadata: dict[str, object]) -> None:
        try:
            self._write_json(path, metadata)
        except OSError:
            LOGGER.warning("Could not persist PPP runtime state at %s", path)

    def _write_metadata(self, profile_id: str, metadata: dict[str, object]) -> None:
        self._write_json(self._metadata_path(profile_id), metadata)

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_metadata(self, profile_id: str) -> dict[str, object] | None:
        return self._read_json(self._metadata_path(profile_id))

    def _read_json(self, path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _remove_metadata(self, metadata: dict[str, object]) -> None:
        profile_id = str(metadata.get("profile_id", "")).strip()
        if profile_id:
            try:
                self._metadata_path(profile_id).unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove PPP runtime metadata for %s", profile_id)

    def _remove_pid_file(self, link_name: str, pid_path: Path) -> None:
        if not link_name or pid_path not in self._pid_paths(link_name):
            return
        try:
            pid_path.unlink(missing_ok=True)
            return
        except PermissionError:
            result = self._run_privileged(
                ["rm", "-f", str(pid_path)],
                timeout=10,
                interactive=True,
            )
            if result.return_code != 0:
                LOGGER.warning("Could not remove PPP PID file %s", pid_path)
        except OSError:
            LOGGER.warning("Could not remove PPP PID file %s", pid_path)

    def _metadata_path(self, profile_id: str) -> Path:
        return self._runtime_dir / f"{self._safe_name(profile_id)}.json"

    def _pid_paths(self, link_name: str) -> tuple[Path, ...]:
        safe_link = self._safe_name(link_name)
        return (Path("/run") / f"ppp-{safe_link}.pid", Path("/var/run") / f"ppp-{safe_link}.pid")

    def _link_name(self, profile: ConnectionProfile) -> str:
        return f"kopdes-{self._safe_name(profile.id)}"

    def _peer_name(self, profile: ConnectionProfile) -> str:
        peer = str(profile.config_payload.get("peer_name", profile.name)).strip()
        return peer or profile.name

    def _safe_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))
        return safe[:100] or "profile"

    def _valid_peer(self, peer: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", peer)) and peer not in {".", ".."}

    def _validate_secret(self, value: str | None) -> str | None:
        if value is not None and any(char in value for char in "\x00\r\n"):
            return "Credentials cannot contain NUL or newline characters."
        return None

    def _as_pid(self, value: object) -> int | None:
        try:
            pid = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return pid if pid > 0 else None

    def _pid_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return isinstance(pid, int) and os.path.exists(f"/proc/{pid}")
        except OSError:
            return False

    def _pid_matches(self, pid_value: object, metadata: dict[str, object]) -> bool:
        pid = self._as_pid(pid_value)
        if pid is None or not self._pid_exists(pid):
            return False
        expected_start = str(metadata.get("pid_start_time", "")).strip()
        actual_start = self._process_start_time(pid)
        if not expected_start or not actual_start or expected_start != actual_start:
            return False
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False
        arguments = [item.decode(errors="replace") for item in raw.split(b"\x00") if item]
        if not arguments or Path(arguments[0]).name != "pppd":
            return False
        link_name = str(metadata.get("linkname", "")).strip()
        return bool(link_name and link_name in arguments)

    def _process_start_time(self, pid: int) -> str | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            remainder = stat[stat.rfind(")") + 2 :].split()
            return remainder[19] if len(remainder) > 19 else None
        except (OSError, IndexError):
            return None

    def _run_privileged(
        self,
        command: list[str],
        timeout: int,
        redact_values: Iterable[str | None] = (),
        stdin_data: str | None = None,
    ) -> CommandResult:
        safe_values = tuple(value for value in redact_values if value)
        runner = getattr(self._command_runner, "run_privileged", None)
        if runner is None:
            try:
                return self._command_runner.run(
                    command, timeout=timeout, redact_values=safe_values, stdin_data=stdin_data
                )
            except TypeError:
                return self._command_runner.run(command, timeout=timeout)
        kwargs: dict[str, object] = {"timeout": timeout, "interactive": True}
        if safe_values:
            kwargs["redact_values"] = safe_values
        if stdin_data is not None:
            kwargs["stdin_data"] = stdin_data
        try:
            return runner(command, **kwargs)
        except TypeError:
            kwargs.pop("stdin_data", None)
            try:
                return runner(command, **kwargs)
            except TypeError:
                return runner(command, timeout=timeout)

    def _result_detail(self, result: CommandResult, secret_values: Iterable[str | None] = ()) -> str:
        detail = result.stderr.strip() or result.stdout.strip()
        for value in sorted((str(item) for item in secret_values if item), key=len, reverse=True):
            detail = detail.replace(value, "<redacted>")
        return detail

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
