from __future__ import annotations

from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult, OpenVpnConfig, OpenVpnSession
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.classic_openvpn_manager import ClassicOpenVpnManager
from kopdes.infrastructure.system.openvpn3_manager import OpenVpn3Manager


class OpenVpnManager:
    def __init__(self, classic_manager: ClassicOpenVpnManager, openvpn3_manager: OpenVpn3Manager) -> None:
        self._classic_manager = classic_manager
        self._openvpn3_manager = openvpn3_manager

    def import_config(self, path: str, alias: str, preferred_backend: str = "openvpn") -> ActionResult:
        backend = self._pick_backend(preferred_backend)
        if backend == "openvpn3":
            result = self._openvpn3_manager.import_config(path, alias)
            result.data.setdefault("openvpn_backend", "openvpn3")
            return result
        result = self._classic_manager.import_config(path, alias)
        result.data.setdefault("openvpn_backend", "openvpn")
        return result

    def list_configs(self) -> list[OpenVpnConfig]:
        configs = self._classic_manager.list_configs()
        configs.extend(self._openvpn3_manager.list_configs())
        return configs

    def list_sessions(self) -> list[OpenVpnSession]:
        sessions = self._classic_manager.list_sessions()
        sessions.extend(self._openvpn3_manager.list_sessions())
        return sessions

    def start_session(self, profile: ConnectionProfile, password: str | None = None) -> ActionResult:
        backend = str(profile.config_payload.get("openvpn_backend", "openvpn"))
        interface_name = str(profile.config_payload.get("interface_name", "")).strip() or None
        if backend == "openvpn3":
            fallback_path = self._classic_config_path(profile)
            if not self._openvpn3_manager.available() and fallback_path:
                return self._classic_manager.start_session(
                    config_path=fallback_path,
                    alias=profile.name,
                    interface_name=interface_name,
                    username=profile.username,
                    password=password,
                    auth_user_pass_required=self._config_bool(profile.config_payload.get("auth_user_pass_required")),
                    auth_user_pass_file=self._config_text(profile.config_payload.get("auth_user_pass_file")),
                )
            config_ref = str(
                profile.config_payload.get("config_path")
                or profile.config_payload.get("openvpn3_config_path")
                or profile.name
            )
            return self._openvpn3_manager.start_session(config_ref)
        config_path = self._classic_config_path(profile) or str(
            Path.home() / ".local" / "share" / "kopdes" / "openvpn" / "profiles" / f"{profile.name}.ovpn"
        )
        return self._classic_manager.start_session(
            config_path=config_path,
            alias=profile.name,
            interface_name=interface_name,
            username=profile.username,
            password=password,
            auth_user_pass_required=self._config_bool(profile.config_payload.get("auth_user_pass_required")),
            auth_user_pass_file=self._config_text(profile.config_payload.get("auth_user_pass_file")),
        )

    def disconnect_profile(self, profile: ConnectionProfile) -> ActionResult:
        backend = str(profile.config_payload.get("openvpn_backend", "openvpn"))
        if backend == "openvpn3":
            if self._openvpn3_manager.available():
                for session in self._openvpn3_manager.list_sessions():
                    if session.name == profile.name:
                        return self._openvpn3_manager.disconnect_session(session.session_path)
            session_path = self._classic_manager.session_path_for_alias(profile.name)
            if session_path:
                return self._classic_manager.disconnect_session(session_path)
            return ActionResult(True, "No active OpenVPN session was found. Profile is already disconnected.")
        session_path = self._classic_manager.session_path_for_alias(profile.name)
        if not session_path:
            return ActionResult(True, "No active OpenVPN session was found. Profile is already disconnected.")
        return self._classic_manager.disconnect_session(session_path)

    def remove_profile(self, profile: ConnectionProfile) -> ActionResult:
        backend = str(profile.config_payload.get("openvpn_backend", "openvpn"))
        classic_config_path = self._classic_config_path(profile)
        config_ref = str(profile.config_payload.get("config_path") or profile.name)
        if backend == "openvpn3":
            if self._openvpn3_manager.available():
                result = self._openvpn3_manager.remove_config(config_ref)
                if result.success:
                    return result
            if classic_config_path:
                return self._normalize_delete_result(
                    self._classic_manager.remove_config(classic_config_path),
                    profile.name,
                )
            return ActionResult(
                True,
                f"Deleted OpenVPN profile '{profile.name}' from KOPDES.",
                "OpenVPN3 is unavailable and no local .ovpn file was present, so only the app record was removed.",
            )
        return self._normalize_delete_result(
            self._classic_manager.remove_config(classic_config_path or config_ref),
            profile.name,
        )

    def read_runtime_logs(self, profile: ConnectionProfile, limit: int = 200) -> list[str]:
        backend = str(profile.config_payload.get("openvpn_backend", "openvpn"))
        config_ref = str(
            profile.config_payload.get("config_path")
            or profile.config_payload.get("openvpn3_config_path")
            or profile.name
        )
        if backend == "openvpn3":
            logs = self._openvpn3_manager.read_runtime_logs(config_ref, limit)
            if logs:
                return logs
        return self._classic_manager.read_runtime_logs(profile.name, limit)

    def _pick_backend(self, preferred_backend: str) -> str:
        if preferred_backend == "openvpn3" and self._openvpn3_manager.available():
            return "openvpn3"
        if self._classic_manager.available():
            return "openvpn"
        if self._openvpn3_manager.available():
            return "openvpn3"
        return "openvpn"

    def _classic_config_path(self, profile: ConnectionProfile) -> str | None:
        config_path = str(profile.config_payload.get("config_path", "")).strip()
        if config_path and Path(config_path).exists():
            return config_path
        fallback = Path.home() / ".local" / "share" / "kopdes" / "openvpn" / "profiles" / f"{profile.name}.ovpn"
        if fallback.exists():
            return str(fallback)
        return None

    def _normalize_delete_result(self, result: ActionResult, profile_name: str) -> ActionResult:
        if result.success:
            return result
        if "was not found" in result.message.lower():
            return ActionResult(
                True,
                f"Deleted OpenVPN profile '{profile_name}' from KOPDES.",
                "No stored .ovpn file remained on disk, so only the app record was removed.",
            )
        return result

    def _config_bool(self, value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _config_text(self, value: object) -> str | None:
        text = str(value or "").strip()
        return text or None
