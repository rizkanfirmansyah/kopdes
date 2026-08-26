from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult, OpenVpnConfig, OpenVpnSession
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandRunner, CommandResult


LOGGER = logging.getLogger(__name__)


class ClassicOpenVpnManager:
    def __init__(self, command_runner: CommandRunner, data_dir: Path) -> None:
        self._command_runner = command_runner
        self._base_dir = data_dir / "openvpn"
        self._profiles_dir = self._base_dir / "profiles"
        self._runtime_dir = self._base_dir / "runtime"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        self._runtime_dir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        return shutil.which("openvpn") is not None

    def import_config(self, path: str, alias: str) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn command is not installed on this system.")
        source = Path(path).expanduser()
        if not source.is_file():
            return ActionResult(False, f"File not found: {path}")
        safe_alias = self._slug(alias)
        destination = self._profiles_dir / f"{safe_alias}.ovpn"
        try:
            shutil.copy2(source, destination)
            os.chmod(destination, 0o600)
            metadata = self._read_config_metadata(destination, source.parent)
        except OSError as exc:
            LOGGER.exception("OpenVPN import failed for %s", source)
            return ActionResult(False, "Could not store the OpenVPN profile.", str(exc))
        return ActionResult(
            True,
            f"Imported OpenVPN profile '{alias}'.",
            f"Stored at {destination}",
            {
                "config_path": str(destination),
                "alias": alias,
                "openvpn_backend": "openvpn",
                "interface_name": str(metadata.get("interface_name", "")),
                "auth_user_pass_required": str(metadata.get("auth_user_pass_required", False)).lower(),
                "auth_user_pass_file": str(metadata.get("auth_user_pass_file", "")),
            },
        )

    def managed_config_path(self, alias: str) -> Path:
        return self._profiles_dir / f"{self._slug(alias)}.ovpn"

    def create_manual_config(self, profile: ConnectionProfile) -> ActionResult:
        """Create a credential-free config for a manually entered OpenVPN profile."""
        if not profile.server_address.strip():
            return ActionResult(False, "OpenVPN server address is required.")
        if any(char in profile.server_address for char in "\r\n"):
            return ActionResult(False, "OpenVPN server address contains an invalid newline.")
        safe_alias = self._slug(profile.name)
        destination = self.managed_config_path(profile.name)
        payload = profile.config_payload
        device = str(payload.get("interface_name", "tun")).strip() or "tun"
        if not re.fullmatch(r"(?:tun|tap)(?:\d+)?", device):
            device = "tun"
        protocol = str(payload.get("openvpn_proto", "udp")).strip().lower()
        if protocol not in {"udp", "tcp"}:
            protocol = "udp"
        port = profile.port or 1194
        lines = [
            "client",
            f"dev {device}",
            f"proto {protocol}",
            f"remote {profile.server_address} {port}",
            "nobind",
            "persist-key",
            "persist-tun",
            "verb 3",
        ]
        if profile.username or self._config_bool(payload.get("auth_user_pass_required")):
            lines.append("auth-user-pass")
        if profile.keepalive:
            lines.extend([f"ping {profile.keepalive}", f"ping-restart {max(profile.keepalive * 3, 30)}"])
        if profile.mtu:
            lines.append(f"tun-mtu {profile.mtu}")
        try:
            destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.chmod(destination, 0o600)
        except OSError as exc:
            LOGGER.exception("Could not create manual OpenVPN config at %s", destination)
            return ActionResult(False, "Could not create the local OpenVPN configuration.", str(exc))
        return ActionResult(
            True,
            f"Prepared manual OpenVPN profile '{profile.name}'.",
            f"Generated credential-free config at {destination}.",
            {"config_path": str(destination)},
        )

    def list_configs(self) -> list[OpenVpnConfig]:
        configs: list[OpenVpnConfig] = []
        for path in sorted(self._profiles_dir.glob("*.ovpn")):
            try:
                imported_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            except OSError:
                continue
            configs.append(
                OpenVpnConfig(
                    name=path.stem,
                    config_path=str(path),
                    backend="openvpn",
                    imported_at=imported_at,
                )
            )
        return configs

    def list_sessions(self) -> list[OpenVpnSession]:
        sessions: list[OpenVpnSession] = []
        for meta_path in sorted(self._runtime_dir.glob("*.json")):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            pid = self._resolve_pid(payload)
            if pid <= 0 or not self._pid_running(pid):
                continue
            payload["pid"] = pid
            try:
                meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except OSError:
                pass
            sessions.append(
                OpenVpnSession(
                    name=str(payload.get("name", meta_path.stem)),
                    session_path=str(meta_path),
                    status_text=self._read_status_text(payload),
                    backend="openvpn",
                    config_path=str(payload.get("config_path", "")) or None,
                    pid=pid,
                    interface_name=self._resolve_interface_name(payload),
                )
            )
        return sessions

    def start_session(
        self,
        config_path: str,
        alias: str,
        interface_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auth_user_pass_required: bool = False,
        auth_user_pass_file: str | None = None,
    ) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn command is not installed on this system.")
        config = Path(config_path).expanduser()
        if not config.is_file():
            return ActionResult(False, "OpenVPN config file was not found.", str(config))
        safe_alias = self._slug(alias)
        if self.session_path_for_alias(alias):
            return ActionResult(False, f"OpenVPN profile '{alias}' is already connected or connecting.")
        pid_path = self._runtime_dir / f"{safe_alias}.pid"
        log_path = self._runtime_dir / f"{safe_alias}.log"
        status_path = self._runtime_dir / f"{safe_alias}.status"
        meta_path = self._runtime_dir / f"{safe_alias}.json"
        prepared = self._prepare_runtime_files(pid_path, log_path, status_path)
        if not prepared.success:
            return prepared
        auth_path: Path | None = None
        command = [
            "openvpn",
            "--config",
            str(config),
            "--daemon",
            f"kopdes-{safe_alias}",
            "--writepid",
            str(pid_path),
            "--log-append",
            str(log_path),
            "--status",
            str(status_path),
            "10",
        ]
        if auth_user_pass_file:
            auth_path = Path(auth_user_pass_file).expanduser()
            if not auth_path.is_file():
                return ActionResult(False, "OpenVPN credentials file was not found.", str(auth_path))
            command.extend(["--auth-user-pass", str(auth_path)])
        elif auth_user_pass_required:
            if not username or not password:
                return ActionResult(
                    False,
                    "This OpenVPN profile requires username and password.",
                    "Edit the profile and save encrypted credentials before connecting.",
                )
            auth_path = self._runtime_dir / f"{safe_alias}.auth"
            try:
                auth_path.write_text(f"{username}\n{password}\n", encoding="utf-8")
                os.chmod(auth_path, 0o600)
            except OSError as exc:
                return ActionResult(False, "Could not prepare OpenVPN credentials.", str(exc))
            command.extend(["--auth-user-pass", str(auth_path), "--auth-nocache"])
        privileged_run = self._privileged_runner()
        result = privileged_run(command, timeout=45, interactive=True)
        if result.return_code != 0:
            if auth_path is not None and auth_path.parent == self._runtime_dir:
                self._unlink_runtime_path(auth_path)
            return ActionResult(False, "OpenVPN session start failed.", self._result_detail(result))
        pid = self._wait_for_pid(pid_path)
        if pid is None:
            return ActionResult(
                False,
                "OpenVPN did not publish a PID file.",
                "The process was not registered by KOPDES and may need to be checked in the runtime log.",
            )
        metadata = {
            "name": alias,
            "config_path": str(config),
            "pid": pid,
            "pid_path": str(pid_path),
            "log_path": str(log_path),
            "status_path": str(status_path),
            "interface_name": interface_name or "",
            "auth_path": str(auth_path) if auth_path and auth_path.parent == self._runtime_dir else "",
        }
        try:
            meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            os.chmod(meta_path, 0o600)
        except OSError as exc:
            LOGGER.exception("Could not persist OpenVPN runtime metadata")
            self._stop_pid(pid)
            self._cleanup_runtime_files(metadata, meta_path)
            return ActionResult(False, "Could not register the OpenVPN session.", str(exc))
        self._fix_runtime_permissions([pid_path, log_path, status_path], attempts=30, interval=0.2)
        return ActionResult(
            True,
            f"Started OpenVPN session for '{alias}'.",
            str(log_path),
            {"session_path": str(meta_path)},
        )

    def disconnect_session(self, session_path: str) -> ActionResult:
        meta_path = Path(session_path).expanduser()
        if not self._is_within(meta_path, self._runtime_dir) or meta_path.suffix != ".json":
            return ActionResult(False, "OpenVPN session metadata path is invalid.")
        if not meta_path.exists():
            return ActionResult(True, "OpenVPN session is already stopped.")
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            return ActionResult(False, "Failed to read OpenVPN session metadata.", str(exc))
        if not isinstance(payload, dict):
            return ActionResult(False, "OpenVPN session metadata is invalid.")
        pid = self._resolve_pid(payload)
        if pid <= 0 or not self._pid_running(pid):
            cleaned = self._cleanup_runtime_files(payload, meta_path)
            return ActionResult(
                True,
                "OpenVPN session was already stopped.",
                None if cleaned else "The process was stopped, but some root-owned runtime files could not be removed.",
            )
        privileged_run = self._privileged_runner()
        result = privileged_run(["kill", str(pid)], timeout=20, interactive=True)
        if result.return_code != 0 and self._pid_running(pid):
            return ActionResult(False, "OpenVPN disconnect failed.", self._result_detail(result))
        if not self._wait_for_exit(pid):
            # A real process gets one hard-stop attempt; a vanished PID is already stopped.
            if Path(f"/proc/{pid}").exists():
                privileged_run(["kill", "-KILL", str(pid)], timeout=20, interactive=True)
                if self._pid_running(pid):
                    return ActionResult(False, "OpenVPN process did not stop.", f"PID {pid} is still running.")
        cleaned = self._cleanup_runtime_files(payload, meta_path)
        if not cleaned:
            return ActionResult(True, "Disconnected OpenVPN session.", "Runtime process stopped; some files need cleanup privileges.")
        return ActionResult(True, "Disconnected OpenVPN session.")

    def stop_all_sessions(self) -> ActionResult:
        """Stop live classic sessions and clean stale metadata owned by KOPDES."""
        failures: list[str] = []
        stopped = 0
        for meta_path in sorted(self._runtime_dir.glob("*.json")):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            pid = self._resolve_pid(payload)
            if pid > 0 and self._pid_running(pid):
                result = self.disconnect_session(str(meta_path))
                if not result.success:
                    failures.append(f"{payload.get('name', meta_path.stem)}: {result.message}")
                    continue
                stopped += 1
            else:
                self._cleanup_runtime_files(payload, meta_path)
        if failures:
            return ActionResult(False, "Some OpenVPN sessions could not be stopped.", "\n".join(failures))
        return ActionResult(True, f"Stopped {stopped} managed OpenVPN session(s).")

    def remove_config(self, config_ref: str) -> ActionResult:
        config_path = Path(config_ref).expanduser()
        if not config_path.exists():
            for candidate in self._profiles_dir.glob("*.ovpn"):
                if candidate.stem == config_ref:
                    config_path = candidate
                    break
        for session in self.list_sessions():
            if session.config_path == str(config_path) or session.name == config_ref or Path(session.name).stem == config_ref:
                disconnect = self.disconnect_session(session.session_path)
                if not disconnect.success:
                    return disconnect
        if not config_path.exists():
            return ActionResult(True, f"OpenVPN profile '{config_ref}' was already removed.")
        if not self._is_within(config_path, self._profiles_dir):
            return ActionResult(
                True,
                f"OpenVPN profile '{config_path.stem}' removed from KOPDES.",
                "The source config was outside KOPDES and was intentionally preserved.",
            )
        try:
            config_path.unlink()
        except OSError as exc:
            return ActionResult(False, "Could not delete the stored OpenVPN profile.", str(exc))
        return ActionResult(True, f"Deleted OpenVPN profile '{config_path.stem}'.")

    def session_path_for_alias(self, alias: str) -> str | None:
        for session in self.list_sessions():
            if session.name == alias:
                return session.session_path
        return None

    def read_runtime_logs(self, alias: str, limit: int = 200) -> list[str]:
        log_path = self._runtime_log_path(alias)
        if log_path is None or not log_path.exists():
            return []
        raw = self._safe_read_text(log_path)
        if raw is None:
            return []
        lines = raw.splitlines()
        if limit <= 0:
            return lines
        return lines[-limit:]

    def _cleanup_runtime_files(self, payload: dict[str, object], meta_path: Path) -> bool:
        cleaned = True
        for key in ["pid_path", "status_path", "auth_path"]:
            value = str(payload.get(key, "")).strip()
            if not value:
                continue
            path = Path(value).expanduser()
            if not self._is_within(path, self._runtime_dir):
                LOGGER.warning("Refusing to clean runtime path outside managed directory: %s", path)
                cleaned = False
                continue
            cleaned = self._unlink_runtime_path(path) and cleaned
        if self._is_within(meta_path, self._runtime_dir):
            cleaned = self._unlink_runtime_path(meta_path) and cleaned
        return cleaned

    def _read_status_text(self, payload: dict[str, object]) -> str:
        status_path = str(payload.get("status_path", "")).strip()
        if status_path:
            path = Path(status_path)
            if path.exists():
                parsed = self._parse_runtime_text(self._safe_read_text(path))
                if parsed:
                    return parsed
        log_path = str(payload.get("log_path", "")).strip()
        if log_path:
            path = Path(log_path)
            if path.exists():
                parsed = self._parse_runtime_text(self._safe_read_text(path))
                if parsed:
                    return parsed
        return "running"

    def _resolve_interface_name(self, payload: dict[str, object]) -> str | None:
        configured = str(payload.get("interface_name", "")).strip()
        if configured and configured not in {"tun", "tap", "ppp"}:
            return configured
        texts: list[str] = []
        for key in ["status_path", "log_path"]:
            value = str(payload.get(key, "")).strip()
            if value:
                raw = self._safe_read_text(Path(value))
                if raw:
                    texts.append(raw)
        match = re.search(r"(?:TUN/TAP device|device)\s+(tun\d+|tap\d+)\s+opened", "\n".join(texts), re.IGNORECASE)
        if match:
            return match.group(1)
        return configured or None

    def _pid_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except PermissionError:
            return self._pid_looks_like_openvpn(pid)
        except OSError:
            return False
        return self._pid_looks_like_openvpn(pid)

    def _wait_for_exit(self, pid: int, attempts: int = 20, interval: float = 0.1) -> bool:
        for _ in range(attempts):
            if not self._pid_running(pid):
                return True
            time.sleep(interval)
        return not self._pid_running(pid)

    def _stop_pid(self, pid: int) -> None:
        if pid <= 0 or not self._pid_running(pid):
            return
        result = self._privileged_runner()(["kill", str(pid)], timeout=20, interactive=True)
        if result.return_code == 0:
            self._wait_for_exit(pid)

    def _prepare_runtime_files(self, *paths: Path) -> ActionResult:
        for path in paths:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.unlink(missing_ok=True)
                path.touch(mode=0o644)
                os.chmod(path, 0o644)
            except OSError:
                result = self._privileged_runner()(["rm", "-f", str(path)], timeout=20, interactive=True)
                if result.return_code != 0:
                    return ActionResult(False, "Could not prepare OpenVPN runtime files.", self._result_detail(result))
                result = self._privileged_runner()(["touch", str(path)], timeout=20, interactive=True)
                if result.return_code != 0:
                    return ActionResult(False, "Could not create OpenVPN runtime files.", self._result_detail(result))
                self._fix_runtime_permissions([path])
        return ActionResult(True, "Runtime files prepared.")

    def _unlink_runtime_path(self, path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            result = self._privileged_runner()(["rm", "-f", str(path)], timeout=20, interactive=True)
            return result.return_code == 0 or not path.exists()

    def _privileged_runner(self):
        return getattr(self._command_runner, "run_privileged", self._command_runner.run)

    def _result_detail(self, result: CommandResult) -> str:
        return result.stderr.strip() or result.stdout.strip()

    def _is_within(self, path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _slug(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "openvpn-profile"

    def _read_config_metadata(self, path: Path, source_dir: Path | None = None) -> dict[str, object]:
        metadata: dict[str, object] = {}
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("dev "):
                metadata["interface_name"] = stripped.split(maxsplit=1)[1]
            elif stripped.startswith("remote "):
                parts = stripped.split()
                if len(parts) >= 2:
                    metadata["server_address"] = parts[1]
            elif stripped.startswith("auth-user-pass"):
                parts = stripped.split(maxsplit=1)
                metadata["auth_user_pass_required"] = True
                if len(parts) == 2:
                    auth_file = Path(parts[1].strip()).expanduser()
                    if not auth_file.is_absolute() and source_dir is not None:
                        candidate = source_dir / auth_file
                        if candidate.exists():
                            auth_file = candidate
                    metadata["auth_user_pass_file"] = str(auth_file)
        return metadata

    def _wait_for_pid(self, pid_path: Path, attempts: int = 20, interval: float = 0.1) -> int | None:
        for _ in range(attempts):
            pid = self._read_pid_file(pid_path)
            if pid is not None:
                return pid
            time.sleep(interval)
        return self._read_pid_file(pid_path)

    def _resolve_pid(self, payload: dict[str, object]) -> int:
        try:
            existing = int(payload.get("pid", 0) or 0)
        except (TypeError, ValueError):
            existing = 0
        if existing > 0:
            return existing
        pid_path = str(payload.get("pid_path", "")).strip()
        if not pid_path:
            return 0
        return self._read_pid_file(Path(pid_path)) or 0

    def _read_pid_file(self, pid_path: Path) -> int | None:
        try:
            if not pid_path.exists():
                return None
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _runtime_log_path(self, alias: str) -> Path | None:
        session_path = self.session_path_for_alias(alias)
        if session_path:
            meta_path = Path(session_path)
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
                log_path = str(payload.get("log_path", "")).strip()
                if log_path:
                    return Path(log_path)
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return self._runtime_dir / f"{self._slug(alias)}.log"

    def _safe_read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

    def _pid_looks_like_openvpn(self, pid: int) -> bool:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        try:
            raw = cmdline_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return True
        normalized = raw.replace("\x00", " ").lower()
        return "openvpn" in normalized

    def _parse_runtime_text(self, raw: str | None) -> str | None:
        if not raw:
            return None
        for line in reversed(raw.lower().splitlines()):
            if "connected,success" in line or "initialization sequence completed" in line:
                return "connected"
            if any(token in line for token in ("auth_failed", "fatal error", "exiting due to fatal error")):
                return "failed"
            if "reconnecting" in line or "restart pause" in line:
                return "reconnecting"
            if any(token in line for token in ("tls:", "push_request", "peer connection initiated", "connecting", "resolving", "wait")):
                return "connecting"
        return None

    def _config_bool(self, value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _fix_runtime_permissions(
        self,
        paths: list[Path],
        attempts: int = 1,
        interval: float = 0.0,
    ) -> None:
        privileged_run = getattr(self._command_runner, "run_privileged", self._command_runner.run)
        seen: set[str] = set()
        for attempt in range(attempts):
            existing = [str(path) for path in paths if path.exists() and str(path) not in seen]
            for existing_path in existing:
                result = privileged_run(["chmod", "644", existing_path], timeout=20)
                if result.return_code == 0:
                    seen.add(existing_path)
            if len(seen) == len({str(path) for path in paths}):
                return
            if attempt < attempts - 1 and interval > 0:
                time.sleep(interval)
