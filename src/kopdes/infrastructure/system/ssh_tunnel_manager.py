from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult, PortMappingSession
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.system.command_runner import CommandRunner


LOGGER = logging.getLogger(__name__)


class SshTunnelManager:
    """Own SSH local-forward processes and their durable runtime metadata."""

    STARTUP_TIMEOUT_SECONDS = 10.0
    STOP_TIMEOUT_SECONDS = 3.0

    def __init__(self, command_runner: CommandRunner, data_dir: Path) -> None:
        self._command_runner = command_runner
        self._runtime_dir = data_dir / "ssh_tunnels" / "runtime"
        self._known_hosts_path = data_dir / "ssh_tunnels" / "known_hosts"
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        self._known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen] = {}
        self._ensure_private_file(self._known_hosts_path)

    def start(self, mapping: PortMapping, password: str | None = None) -> ActionResult:
        validation_error = self.validate_mapping(mapping, password)
        if validation_error:
            return ActionResult(False, "SSH port mapping validation failed.", validation_error)
        if shutil.which("ssh") is None:
            return ActionResult(False, "OpenSSH client is not installed.", "Install the 'openssh-client' package.")
        if password and shutil.which("sshpass") is None:
            return ActionResult(
                False,
                "Password-based SSH mapping is unavailable.",
                "Install 'sshpass' or configure an SSH identity key/agent for this mapping.",
            )

        existing = self._read_session_metadata(mapping.id)
        if existing and self._pid_matches(existing.get("pid"), existing):
            listening = self._is_local_listener(mapping)
            state = PortMappingSession(
                mapping_id=mapping.id,
                name=mapping.name,
                status_text="active" if listening else "connecting",
                pid=int(existing["pid"]),
                local_listening=listening,
            )
            return ActionResult(
                True,
                "SSH port mapping is already running.",
                data={"mapping_id": mapping.id, "pid": str(state.pid)},
            )
        if existing:
            self._remove_metadata(mapping.id)

        if self._local_port_is_busy(mapping):
            return ActionResult(
                False,
                "Local port is already in use.",
                f"Cannot bind {mapping.local_host}:{mapping.local_port}. Choose another local port.",
            )

        command = self._build_ssh_command(mapping, bool(password))
        log_path = self._log_path(mapping.id)
        log_handle = None
        read_fd = write_fd = None
        process = None
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            os.chmod(log_path, 0o600)
            if password:
                read_fd, write_fd = os.pipe()
                process = subprocess.Popen(
                    ["sshpass", "-d", str(read_fd), *command],
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    pass_fds=(read_fd,),
                    close_fds=True,
                    env={**os.environ, "LC_ALL": "C"},
                )
            else:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                    env={**os.environ, "LC_ALL": "C"},
                )
            if write_fd is not None:
                secret = password.encode("utf-8") + b"\n"
                while secret:
                    written = os.write(write_fd, secret)
                    secret = secret[written:]
        except FileNotFoundError as exc:
            if process is not None:
                self._terminate_pid(process.pid)
            return ActionResult(False, "SSH client could not be started.", str(exc))
        except PermissionError as exc:
            if process is not None:
                self._terminate_pid(process.pid)
            return ActionResult(False, "Permission denied while starting SSH mapping.", str(exc))
        except OSError as exc:
            if process is not None:
                self._terminate_pid(process.pid)
            LOGGER.exception("Could not start SSH mapping %s", mapping.name)
            return ActionResult(False, "SSH port mapping could not be started.", str(exc))
        finally:
            for fd in (read_fd, write_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if log_handle is not None:
                log_handle.close()

        metadata = {
            "mapping_id": mapping.id,
            "name": mapping.name,
            "pid": process.pid,
            "pid_start_time": self._process_start_time(process.pid),
            "local_host": mapping.local_host,
            "local_port": mapping.local_port,
            "remote_host": mapping.remote_host,
            "remote_port": mapping.remote_port,
            "ssh_host": mapping.ssh_host,
            "ssh_port": mapping.ssh_port,
            "ssh_username": mapping.ssh_username,
            "log_path": str(log_path),
        }
        try:
            self._write_metadata(mapping.id, metadata)
            self._processes[mapping.id] = process
        except OSError as exc:
            LOGGER.exception("Could not persist SSH mapping metadata for %s", mapping.name)
            self._terminate_pid(process.pid)
            return ActionResult(False, "SSH mapping metadata could not be saved.", str(exc))

        deadline = time.monotonic() + self.STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                details = self._read_log_tail(log_path)
                self._remove_metadata(mapping.id)
                return ActionResult(
                    False,
                    "SSH port mapping exited before it became available.",
                    details or f"ssh exited with status {return_code}.",
                )
            if self._is_local_listener(mapping):
                return ActionResult(
                    True,
                    f"SSH port mapping '{mapping.name}' is active.",
                    data={"mapping_id": mapping.id, "pid": str(process.pid)},
                )
            time.sleep(0.2)

        return ActionResult(
            True,
            f"SSH port mapping '{mapping.name}' is connecting.",
            "The SSH process is alive but the local listener has not been confirmed yet.",
            {"mapping_id": mapping.id, "pid": str(process.pid)},
        )

    def list_sessions(self) -> list[PortMappingSession]:
        sessions: list[PortMappingSession] = []
        for metadata_path in sorted(self._runtime_dir.glob("*.json")):
            metadata = self._read_json(metadata_path)
            if not metadata:
                continue
            mapping_id = str(metadata.get("mapping_id", "")).strip()
            if not mapping_id:
                continue
            pid = self._as_pid(metadata.get("pid"))
            if not self._pid_matches(pid, metadata):
                self._processes.pop(mapping_id, None)
                continue
            process = self._processes.get(mapping_id)
            if process is not None and process.poll() is not None:
                self._processes.pop(mapping_id, None)
                self._remove_metadata(mapping_id)
                continue
            local_host = str(metadata.get("local_host", "127.0.0.1"))
            local_port = self._as_port(metadata.get("local_port"))
            listening = self._is_local_listener_values(local_host, local_port)
            sessions.append(
                PortMappingSession(
                    mapping_id=mapping_id,
                    name=str(metadata.get("name", mapping_id)),
                    status_text="active" if listening else "connecting",
                    pid=pid,
                    local_listening=listening,
                )
            )
        return sessions

    def stop(self, mapping_id: str) -> ActionResult:
        mapping_id = str(mapping_id or "").strip()
        if not mapping_id:
            return ActionResult(False, "SSH mapping id is required.")
        metadata = self._read_session_metadata(mapping_id)
        if not metadata:
            return ActionResult(True, "SSH port mapping is already stopped.")
        pid = self._as_pid(metadata.get("pid"))
        if pid is None or not self._pid_matches(pid, metadata):
            self._remove_metadata(mapping_id)
            return ActionResult(True, "Stale SSH port mapping state was cleaned up.")

        if not self._terminate_pid(pid):
            return ActionResult(
                False,
                "SSH port mapping could not be stopped.",
                f"The managed SSH process {pid} is still running or permission was denied.",
            )
        process = self._processes.pop(mapping_id, None)
        if process is not None:
            try:
                process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        self._remove_metadata(mapping_id)
        return ActionResult(True, "SSH port mapping stopped.")

    def stop_all(self) -> ActionResult:
        failures: list[str] = []
        for metadata_path in sorted(self._runtime_dir.glob("*.json")):
            metadata = self._read_json(metadata_path)
            mapping_id = str(metadata.get("mapping_id", "")).strip() if metadata else ""
            if not mapping_id:
                try:
                    metadata_path.unlink(missing_ok=True)
                except OSError:
                    failures.append(metadata_path.name)
                continue
            result = self.stop(mapping_id)
            if not result.success:
                failures.append(f"{mapping_id}: {result.details or result.message}")
        if failures:
            return ActionResult(False, "Some SSH port mappings could not be stopped.", "\n".join(failures))
        return ActionResult(True, "Stopped all managed SSH port mappings.")

    def shutdown(self, mappings=None) -> ActionResult:
        del mappings
        return self.stop_all()

    def validate_mapping(self, mapping: PortMapping, password: str | None = None) -> str | None:
        fields = {
            "SSH host": mapping.ssh_host,
            "SSH username": mapping.ssh_username,
            "Local host": mapping.local_host,
            "Remote host": mapping.remote_host,
            "Mapping name": mapping.name,
        }
        for label, value in fields.items():
            if not str(value or "").strip():
                return f"{label} is required."
            if any(char in str(value) for char in "\r\n\x00"):
                return f"{label} contains an invalid control character."
            if any(char.isspace() for char in str(value)):
                return f"{label} must not contain whitespace."
        for label, value in (
            ("SSH port", mapping.ssh_port),
            ("Local port", mapping.local_port),
            ("Remote port", mapping.remote_port),
        ):
            try:
                valid = 1 <= int(value) <= 65535
            except (TypeError, ValueError):
                valid = False
            if not valid:
                return f"{label} must be between 1 and 65535."
        if int(mapping.local_port) < 1024:
            return "Local port must be 1024 or higher so KOPDES does not require root for SSH."
        if mapping.identity_file:
            identity = Path(mapping.identity_file).expanduser()
            if not identity.is_file():
                return f"SSH identity file does not exist: {identity}"
            if any(char in str(identity) for char in "\r\n\x00"):
                return "SSH identity file contains an invalid control character."
        if password is not None and any(char in password for char in "\x00"):
            return "SSH password contains an unsupported null character."
        return None

    def _build_ssh_command(self, mapping: PortMapping, with_password: bool = False) -> list[str]:
        local_endpoint = f"{mapping.local_host}:{mapping.local_port}:{mapping.remote_host}:{mapping.remote_port}"
        command = [
            "ssh",
            "-N",
            "-T",
            "-L",
            local_endpoint,
            "-p",
            str(mapping.ssh_port),
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self._known_hosts_path}",
        ]
        if with_password:
            command.extend(["-o", "PubkeyAuthentication=no"])
        elif mapping.identity_file:
            command.extend(["-i", str(Path(mapping.identity_file).expanduser()), "-o", "IdentitiesOnly=yes"])
        else:
            command.extend(["-o", "BatchMode=yes"])
        command.append(f"{mapping.ssh_username}@{mapping.ssh_host}")
        return command

    def _local_port_is_busy(self, mapping: PortMapping) -> bool:
        host = mapping.local_host
        if host in {"0.0.0.0", "::", ""}:
            host = "::" if ":" in mapping.local_host else "0.0.0.0"
        try:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, int(mapping.local_port)))
            return False
        except OSError:
            return True

    def _is_local_listener(self, mapping: PortMapping) -> bool:
        return self._is_local_listener_values(mapping.local_host, mapping.local_port)

    def _is_local_listener_values(self, host: str, port: int | None) -> bool:
        if port is None:
            return False
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
        try:
            with socket.create_connection((probe_host, int(port)), timeout=0.25):
                return True
        except (OSError, ValueError):
            return False

    def _terminate_pid(self, pid: int) -> bool:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            result = self._command_runner.run_privileged(["kill", "-TERM", str(pid)], interactive=True)
            if result.return_code != 0:
                return False
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            except PermissionError:
                result = self._command_runner.run_privileged(["kill", "-TERM", str(pid)], interactive=True)
                if result.return_code != 0:
                    return False

        deadline = time.monotonic() + self.STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_exists(pid):
                return True
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            result = self._command_runner.run_privileged(["kill", "-KILL", str(pid)], interactive=True)
            return result.return_code == 0 and not self._pid_exists(pid)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            except PermissionError:
                result = self._command_runner.run_privileged(["kill", "-KILL", str(pid)], interactive=True)
                return result.return_code == 0 and not self._pid_exists(pid)
        return not self._pid_exists(pid)

    def _pid_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return isinstance(pid, int) and os.path.exists(f"/proc/{pid}")
        except OSError:
            return False

    def _pid_matches(self, pid_value, metadata: dict) -> bool:
        pid = self._as_pid(pid_value)
        if pid is None or not self._pid_exists(pid):
            return False
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
        except OSError:
            return False
        executable = Path(cmdline.split(" ", 1)[0]).name
        target = f"{metadata.get('ssh_username', '')}@{metadata.get('ssh_host', '')}"
        local_endpoint = (
            f"{metadata.get('local_host', '')}:{metadata.get('local_port', '')}:"
            f"{metadata.get('remote_host', '')}:{metadata.get('remote_port', '')}"
        )
        expected_start = metadata.get("pid_start_time")
        actual_start = self._process_start_time(pid)
        if expected_start and actual_start and str(expected_start) != str(actual_start):
            return False
        return (
            executable in {"ssh", "sshpass"}
            and " -L " in f" {cmdline} "
            and " -N " in f" {cmdline} "
            and target in cmdline
            and local_endpoint in cmdline
        )

    def _process_start_time(self, pid: int) -> str | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            remainder = stat[stat.rfind(")") + 2 :].split()
            return remainder[19] if len(remainder) > 19 else None
        except (OSError, IndexError):
            return None

    def _metadata_path(self, mapping_id: str) -> Path:
        return self._runtime_dir / f"{self._safe_name(mapping_id)}.json"

    def _log_path(self, mapping_id: str) -> Path:
        return self._runtime_dir / f"{self._safe_name(mapping_id)}.log"

    def _safe_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))
        return safe[:120] or "mapping"

    def _read_session_metadata(self, mapping_id: str) -> dict | None:
        return self._read_json(self._metadata_path(mapping_id))

    def _read_json(self, path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _write_metadata(self, mapping_id: str, metadata: dict) -> None:
        target = self._metadata_path(mapping_id)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)

    def _remove_metadata(self, mapping_id: str) -> None:
        try:
            self._metadata_path(mapping_id).unlink(missing_ok=True)
        except OSError:
            LOGGER.exception("Could not remove SSH mapping metadata for %s", mapping_id)

    def _read_log_tail(self, path: Path, limit: int = 30) -> str:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-limit:])

    def _ensure_private_file(self, path: Path) -> None:
        try:
            path.touch(exist_ok=True)
            os.chmod(path, 0o600)
        except OSError:
            LOGGER.warning("Could not prepare private SSH known-hosts file %s", path)

    def _as_pid(self, value) -> int | None:
        try:
            pid = int(value)
        except (TypeError, ValueError):
            return None
        return pid if pid > 1 else None

    def _as_port(self, value) -> int | None:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return None
        return port if 1 <= port <= 65535 else None
