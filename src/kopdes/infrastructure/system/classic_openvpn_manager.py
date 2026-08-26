from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult, OpenVpnConfig, OpenVpnSession
from kopdes.infrastructure.system.command_runner import CommandRunner


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
        source = Path(path)
        if not source.exists():
            return ActionResult(False, f"File not found: {path}")
        safe_alias = self._slug(alias)
        destination = self._profiles_dir / f"{safe_alias}.ovpn"
        shutil.copy2(source, destination)
        metadata = self._read_config_metadata(destination)
        return ActionResult(
            True,
            f"Imported OpenVPN profile '{alias}'.",
            f"Stored at {destination}",
            {
                "config_path": str(destination),
                "alias": alias,
                "openvpn_backend": "openvpn",
                "interface_name": metadata.get("interface_name", ""),
                "auth_user_pass_required": str(metadata.get("auth_user_pass_required", False)).lower(),
                "auth_user_pass_file": str(metadata.get("auth_user_pass_file", "")),
            },
        )

    def list_configs(self) -> list[OpenVpnConfig]:
        configs: list[OpenVpnConfig] = []
        for path in sorted(self._profiles_dir.glob("*.ovpn")):
            configs.append(
                OpenVpnConfig(
                    name=path.stem,
                    config_path=str(path),
                    backend="openvpn",
                    imported_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                )
            )
        return configs

    def list_sessions(self) -> list[OpenVpnSession]:
        sessions: list[OpenVpnSession] = []
        for meta_path in sorted(self._runtime_dir.glob("*.json")):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
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
                    interface_name=str(payload.get("interface_name", "")) or None,
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
        safe_alias = self._slug(alias)
        pid_path = self._runtime_dir / f"{safe_alias}.pid"
        log_path = self._runtime_dir / f"{safe_alias}.log"
        status_path = self._runtime_dir / f"{safe_alias}.status"
        meta_path = self._runtime_dir / f"{safe_alias}.json"
        auth_path = None
        command = [
            "openvpn",
            "--config",
            config_path,
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
            command.extend(["--auth-user-pass", auth_user_pass_file])
        elif auth_user_pass_required:
            if not username or not password:
                return ActionResult(
                    False,
                    "This OpenVPN profile requires username and password.",
                    "Re-import the profile with credentials or edit the profile before connecting.",
                )
            auth_path = self._runtime_dir / f"{safe_alias}.auth"
            auth_path.write_text(f"{username}\n{password}\n", encoding="utf-8")
            os.chmod(auth_path, 0o600)
            command.extend(["--auth-user-pass", str(auth_path), "--auth-nocache"])
        privileged_run = getattr(self._command_runner, "run_privileged", self._command_runner.run)
        result = privileged_run(command, timeout=45, interactive=True)
        if result.return_code != 0:
            if auth_path is not None:
                auth_path.unlink(missing_ok=True)
            return ActionResult(False, "OpenVPN session start failed.", result.stderr.strip() or result.stdout.strip())
        pid = self._wait_for_pid(pid_path)
        self._fix_runtime_permissions([pid_path, log_path, status_path], attempts=30, interval=0.2)
        metadata = {
            "name": alias,
            "config_path": config_path,
            "pid": pid,
            "pid_path": str(pid_path),
            "log_path": str(log_path),
            "status_path": str(status_path),
            "interface_name": interface_name or "",
            "auth_path": str(auth_path) if auth_path else "",
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return ActionResult(True, f"Started OpenVPN session for '{alias}'.", str(log_path), {"session_path": str(meta_path)})

    def disconnect_session(self, session_path: str) -> ActionResult:
        meta_path = Path(session_path)
        if not meta_path.exists():
            return ActionResult(False, "OpenVPN session metadata not found.")
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ActionResult(False, "Failed to read OpenVPN session metadata.", str(exc))
        pid = self._resolve_pid(payload)
        if pid <= 0:
            self._cleanup_runtime_files(payload, meta_path)
            return ActionResult(True, "OpenVPN session metadata cleaned up.")
        privileged_run = getattr(self._command_runner, "run_privileged", self._command_runner.run)
        result = privileged_run(["kill", str(pid)], timeout=20, interactive=True)
        if result.return_code != 0 and self._pid_running(pid):
            return ActionResult(False, "OpenVPN disconnect failed.", result.stderr.strip() or result.stdout.strip())
        self._cleanup_runtime_files(payload, meta_path)
        return ActionResult(True, "Disconnected OpenVPN session.")

    def remove_config(self, config_ref: str) -> ActionResult:
        config_path = Path(config_ref)
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
        if config_path.exists():
            config_path.unlink()
            return ActionResult(True, f"Deleted OpenVPN profile '{config_path.stem}'.")
        return ActionResult(False, f"OpenVPN profile '{config_ref}' was not found.")

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

    def _cleanup_runtime_files(self, payload: dict[str, object], meta_path: Path) -> None:
        for key in ["pid_path", "status_path", "auth_path"]:
            value = str(payload.get(key, "")).strip()
            if value:
                Path(value).unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    def _read_status_text(self, payload: dict[str, object]) -> str:
        status_path = str(payload.get("status_path", "")).strip()
        if status_path:
            path = Path(status_path)
            if path.exists():
                raw = self._safe_read_text(path)
                parsed = self._parse_runtime_text(raw)
                if parsed:
                    return parsed
        log_path = str(payload.get("log_path", "")).strip()
        if log_path:
            path = Path(log_path)
            if path.exists():
                raw = self._safe_read_text(path)
                parsed = self._parse_runtime_text(raw)
                if parsed:
                    return parsed
        return "running"

    def _pid_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except PermissionError:
            return self._pid_looks_like_openvpn(pid)
        except OSError:
            return False
        return self._pid_looks_like_openvpn(pid)

    def _slug(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "openvpn-profile"

    def _read_config_metadata(self, path: Path) -> dict[str, object]:
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
                    metadata["auth_user_pass_file"] = parts[1].strip()
        return metadata

    def _wait_for_pid(self, pid_path: Path, attempts: int = 20, interval: float = 0.1) -> int | None:
        for _ in range(attempts):
            pid = self._read_pid_file(pid_path)
            if pid is not None:
                return pid
            time.sleep(interval)
        return self._read_pid_file(pid_path)

    def _resolve_pid(self, payload: dict[str, object]) -> int:
        existing = int(payload.get("pid", 0) or 0)
        if existing > 0:
            return existing
        pid_path = str(payload.get("pid_path", "")).strip()
        if not pid_path:
            return 0
        return self._read_pid_file(Path(pid_path)) or 0

    def _read_pid_file(self, pid_path: Path) -> int | None:
        if not pid_path.exists():
            return None
        try:
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
            except (OSError, json.JSONDecodeError):
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
        normalized = raw.lower()
        if "connected,success" in normalized or "initialization sequence completed" in normalized:
            return "connected"
        if "auth_failed" in normalized or "fatal error" in normalized or "exiting due to fatal error" in normalized:
            return "failed"
        if "reconnecting" in normalized or "restart pause" in normalized:
            return "reconnecting"
        if any(token in normalized for token in ("tls:", "push_request", "peer connection initiated", "connecting", "resolving", "wait")):
            return "connecting"
        return None

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
            if existing:
                result = privileged_run(["chmod", "644", *existing], timeout=20)
                if result.return_code == 0:
                    seen.update(existing)
            if len(seen) == len({str(path) for path in paths}):
                return
            if attempt < attempts - 1 and interval > 0:
                time.sleep(interval)
