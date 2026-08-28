from __future__ import annotations

import re
import shutil
from functools import wraps
from threading import RLock

from kopdes.application.dtos.runtime_state import ActionResult, OpenVpnConfig, OpenVpnSession
from kopdes.infrastructure.system.command_runner import CommandRunner


def _manager_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class OpenVpn3Manager:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner
        self._lock = RLock()

    def available(self) -> bool:
        return shutil.which("openvpn3") is not None

    @_manager_locked
    def import_config(self, path: str, alias: str) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn3 is not installed on this system.")
        result = self._command_runner.run(
            [
                "openvpn3",
                "config-import",
                "--config",
                path,
                "--name",
                alias,
                "--persistent",
            ],
            timeout=90,
        )
        if result.return_code != 0:
            return ActionResult(False, "OpenVPN3 import failed.", result.stderr.strip())
        config_path = self._extract_first_value(result.stdout, ("Config path", "Configuration path"))
        return ActionResult(
            True,
            f"Imported OpenVPN3 profile '{alias}'.",
            result.stdout.strip(),
            {"config_path": config_path or alias, "alias": alias, "openvpn_backend": "openvpn3"},
        )

    @_manager_locked
    def list_configs(self) -> list[OpenVpnConfig]:
        if not self.available():
            return []
        result = self._command_runner.run(["openvpn3", "configs-list"], timeout=30)
        if result.return_code != 0:
            return []
        configs: list[OpenVpnConfig] = []
        for block in self._split_blocks(result.stdout):
            fields = self._parse_block(block)
            config_path = (
                fields.get("configuration path")
                or fields.get("config path")
                or fields.get("path")
            )
            name = fields.get("name") or fields.get("config name")
            if not config_path or not name:
                continue
            configs.append(
                OpenVpnConfig(
                    name=name,
                    config_path=config_path,
                    backend="openvpn3",
                    imported_at=fields.get("imported"),
                )
            )
        return configs

    @_manager_locked
    def list_sessions(self) -> list[OpenVpnSession]:
        if not self.available():
            return []
        result = self._command_runner.run(["openvpn3", "sessions-list"], timeout=30)
        if result.return_code != 0:
            return []
        sessions: list[OpenVpnSession] = []
        for block in self._split_blocks(result.stdout):
            fields = self._parse_block(block)
            session_path = fields.get("path") or fields.get("session path")
            name = fields.get("config name") or fields.get("name")
            status_text = fields.get("status", "unknown")
            config_path = fields.get("config path") or fields.get("configuration path")
            if not session_path or not name:
                continue
            sessions.append(
                OpenVpnSession(
                    name=name,
                    session_path=session_path,
                    status_text=status_text,
                    backend="openvpn3",
                    config_path=config_path,
                )
            )
        return sessions

    @_manager_locked
    def start_session(self, config_ref: str) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn3 is not installed on this system.")
        result = self._command_runner.run(
            ["openvpn3", "session-start", "--config", config_ref],
            timeout=90,
        )
        if result.return_code != 0:
            return ActionResult(False, "OpenVPN3 session start failed.", result.stderr.strip())
        return ActionResult(True, f"Started OpenVPN3 session for '{config_ref}'.", result.stdout.strip())

    @_manager_locked
    def disconnect_session(self, session_path: str) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn3 is not installed on this system.")
        result = self._command_runner.run(
            ["openvpn3", "session-manage", "--session-path", session_path, "--disconnect"],
            timeout=45,
        )
        if result.return_code != 0:
            return ActionResult(False, "OpenVPN3 disconnect failed.", result.stderr.strip())
        return ActionResult(True, "Disconnected OpenVPN3 session.", result.stdout.strip())

    @_manager_locked
    def remove_config(self, config_ref: str) -> ActionResult:
        if not self.available():
            return ActionResult(False, "openvpn3 is not installed on this system.")
        result = self._command_runner.run(
            ["openvpn3", "config-remove", "--config", config_ref],
            timeout=45,
        )
        if result.return_code != 0:
            return ActionResult(False, "OpenVPN3 config removal failed.", result.stderr.strip())
        return ActionResult(True, f"Deleted OpenVPN3 profile '{config_ref}'.", result.stdout.strip())

    def read_runtime_logs(self, config_ref: str, limit: int = 200) -> list[str]:
        del config_ref, limit
        return []

    def _split_blocks(self, raw: str) -> list[str]:
        return [block.strip() for block in re.split(r"\n\s*\n", raw) if block.strip()]

    def _parse_block(self, block: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            parsed[key.strip().lower()] = value.strip()
        return parsed

    def _extract_first_value(self, raw: str, keys: tuple[str, ...]) -> str | None:
        for key in keys:
            match = re.search(rf"{re.escape(key)}\s*:\s*(.+)", raw)
            if match:
                return match.group(1).strip()
        return None
