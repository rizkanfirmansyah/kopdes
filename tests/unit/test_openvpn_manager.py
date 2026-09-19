from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult, OpenVpnSession
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.openvpn_manager import OpenVpnManager
from kopdes.shared.enums import ProtocolType


class ClassicManagerStub:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, str | None, str | None, str | None, bool, str | None]] = []
        self.removed: list[str] = []

    def available(self) -> bool:
        return True

    def import_config(self, path: str, alias: str) -> ActionResult:
        return ActionResult(True, "imported", data={"config_path": path, "alias": alias})

    def list_configs(self) -> list:
        return []

    def list_sessions(self) -> list:
        return []

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
        self.started.append((config_path, alias, interface_name, username, password, auth_user_pass_required, auth_user_pass_file))
        return ActionResult(True, f"started {alias}")

    def session_path_for_alias(self, alias: str) -> str | None:
        return None

    def disconnect_session(self, session_path: str) -> ActionResult:
        return ActionResult(True, "disconnected")

    def remove_config(self, config_ref: str) -> ActionResult:
        self.removed.append(config_ref)
        if config_ref.endswith("missing.ovpn"):
            return ActionResult(False, "OpenVPN profile 'missing' was not found.")
        return ActionResult(True, "removed")

    def read_runtime_logs(self, alias: str, limit: int = 200) -> list[str]:
        return [f"runtime {alias}"]


class OpenVpn3ManagerStub:
    def __init__(self, available: bool = False) -> None:
        self._available = available

    def available(self) -> bool:
        return self._available

    def import_config(self, path: str, alias: str) -> ActionResult:
        return ActionResult(True, "imported")

    def list_configs(self) -> list:
        return []

    def list_sessions(self) -> list:
        return []

    def start_session(self, config_ref: str) -> ActionResult:
        return ActionResult(False, "openvpn3 is not installed on this system.")

    def disconnect_session(self, session_path: str) -> ActionResult:
        return ActionResult(False, "openvpn3 is not installed on this system.")

    def remove_config(self, config_ref: str) -> ActionResult:
        return ActionResult(False, "openvpn3 is not installed on this system.")

    def read_runtime_logs(self, config_ref: str, limit: int = 200) -> list[str]:
        return []


class OpenVpn3RemovalFailureStub(OpenVpn3ManagerStub):
    def __init__(self) -> None:
        super().__init__(available=True)

    def remove_config(self, config_ref: str) -> ActionResult:
        return ActionResult(False, "OpenVPN3 config removal failed.", "backend refused removal")


def build_profile(config_payload: dict[str, object]) -> ConnectionProfile:
    return ConnectionProfile(
        id="profile-1",
        name="MJLY",
        description="test profile",
        server_address="vpn.example.net",
        protocol=ProtocolType.OPENVPN,
        username="riezkan",
        config_payload=config_payload,
    )


def test_start_session_falls_back_to_classic_when_openvpn3_is_unavailable(tmp_path: Path) -> None:
    ovpn_path = tmp_path / "legacy.ovpn"
    ovpn_path.write_text("client\nremote vpn.example.net 1194\n", encoding="utf-8")
    classic = ClassicManagerStub()
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(available=False))

    result = manager.start_session(
        build_profile(
            {
                "openvpn_backend": "openvpn3",
                "config_path": str(ovpn_path),
                "interface_name": "tun0",
            }
        ),
        password="secret",
    )

    assert result.success is True
    assert classic.started == [(str(ovpn_path), "MJLY", "tun0", "riezkan", "secret", False, None)]


def test_start_session_passes_auth_user_pass_flags_to_classic_backend(tmp_path: Path) -> None:
    ovpn_path = tmp_path / "auth.ovpn"
    ovpn_path.write_text("client\nauth-user-pass\n", encoding="utf-8")
    classic = ClassicManagerStub()
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(available=False))

    result = manager.start_session(
        build_profile(
            {
                "openvpn_backend": "openvpn",
                "config_path": str(ovpn_path),
                "auth_user_pass_required": True,
            }
        ),
        password="secret",
    )

    assert result.success is True
    assert classic.started[-1] == (str(ovpn_path), "MJLY", None, "riezkan", "secret", True, None)


def test_remove_profile_succeeds_when_local_ovpn_file_is_missing() -> None:
    classic = ClassicManagerStub()
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(available=False))

    result = manager.remove_profile(
        build_profile(
            {
                "openvpn_backend": "openvpn",
                "config_path": "missing.ovpn",
            }
        )
    )

    assert result.success is True
    assert "only the app record was removed" in (result.details or "").lower()


def test_remove_profile_succeeds_for_legacy_openvpn3_profile_without_openvpn3() -> None:
    classic = ClassicManagerStub()
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(available=False))

    result = manager.remove_profile(build_profile({"openvpn_backend": "openvpn3"}))

    assert result.success is True
    assert "openvpn3 is unavailable" in (result.details or "").lower()


def test_remove_profile_does_not_hide_openvpn3_backend_failure() -> None:
    classic = ClassicManagerStub()
    manager = OpenVpnManager(classic, OpenVpn3RemovalFailureStub())

    result = manager.remove_profile(build_profile({"openvpn_backend": "openvpn3"}))

    assert result.success is False
    assert result.message == "OpenVPN3 config removal failed."
    assert classic.removed == []


class ClassicManagerWithManual(ClassicManagerStub):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def managed_config_path(self, _alias: str) -> Path:
        return self.path

    def create_manual_config(self, profile: ConnectionProfile) -> ActionResult:
        self.path.write_text("client\n", encoding="utf-8")
        return ActionResult(True, "generated", data={"config_path": str(self.path)})


class OpenVpn3ManagerRecording(OpenVpn3ManagerStub):
    def __init__(self, available: bool = True) -> None:
        super().__init__(available)
        self.started: list[str] = []
        self.disconnected: list[str] = []
        self.removed: list[str] = []
        self.sessions: list = []

    def start_session(self, config_ref: str) -> ActionResult:
        self.started.append(config_ref)
        return ActionResult(True, "openvpn3 started")

    def list_sessions(self) -> list:
        return self.sessions

    def disconnect_session(self, session_path: str) -> ActionResult:
        self.disconnected.append(session_path)
        return ActionResult(True, "openvpn3 disconnected")

    def remove_config(self, config_ref: str) -> ActionResult:
        self.removed.append(config_ref)
        return ActionResult(True, "openvpn3 removed")

    def read_runtime_logs(self, config_ref: str, limit: int = 200) -> list[str]:
        return [f"openvpn3 {config_ref}"]


def test_openvpn_manager_selects_preferred_backend_and_combines_configs(monkeypatch) -> None:
    classic = ClassicManagerStub()
    openvpn3 = OpenVpn3ManagerRecording(True)
    manager = OpenVpnManager(classic, openvpn3)

    imported = manager.import_config("x.ovpn", "X", preferred_backend="openvpn3")

    assert imported.success is True
    assert imported.data["openvpn_backend"] == "openvpn3"
    assert manager.list_configs() == []


def test_openvpn_manager_generates_classic_config_when_missing(tmp_path: Path) -> None:
    classic = ClassicManagerWithManual(tmp_path / "generated.ovpn")
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(False))

    result = manager.start_session(build_profile({"openvpn_backend": "openvpn"}))

    assert result.success is True
    assert classic.started[0][0] == str(tmp_path / "generated.ovpn")


def test_openvpn_manager_uses_available_openvpn3_session(tmp_path: Path) -> None:
    classic = ClassicManagerStub()
    openvpn3 = OpenVpn3ManagerRecording(True)
    manager = OpenVpnManager(classic, openvpn3)

    result = manager.start_session(
        build_profile(
            {
                "openvpn_backend": "openvpn3",
                "config_path": str(tmp_path / "unused.ovpn"),
                "openvpn3_config_path": "/config/ref",
            }
        )
    )

    assert result.success is True
    assert openvpn3.started == [str(tmp_path / "unused.ovpn")]
    assert classic.started == []


def test_openvpn_manager_disconnects_matching_classic_and_openvpn3_sessions() -> None:
    classic = ClassicManagerStub()
    openvpn3 = OpenVpn3ManagerRecording(True)
    openvpn3.sessions = [
        OpenVpnSession(name="MJLY", session_path="/session/mjly", status_text="connected", backend="openvpn3")
    ]
    manager = OpenVpnManager(classic, openvpn3)

    result = manager.disconnect_profile(build_profile({"openvpn_backend": "openvpn3"}))

    assert result.success is True
    assert openvpn3.disconnected == ["/session/mjly"]


def test_openvpn_manager_disconnects_classic_session_when_openvpn3_is_unavailable(monkeypatch) -> None:
    class ActiveClassic(ClassicManagerStub):
        def session_path_for_alias(self, alias: str) -> str | None:
            return f"/session/{alias}"

    classic = ActiveClassic()
    manager = OpenVpnManager(classic, OpenVpn3ManagerStub(False))

    result = manager.disconnect_profile(build_profile({"openvpn_backend": "openvpn3"}))

    assert result.success is True


def test_openvpn_manager_shutdown_filters_openvpn3_names() -> None:
    classic = ClassicManagerStub()

    class ShutdownClassic(ClassicManagerStub):
        def stop_all_sessions(self) -> ActionResult:
            return ActionResult(True, "classic stopped")

    openvpn3 = OpenVpn3ManagerRecording(True)
    openvpn3.sessions = [
        OpenVpnSession(name="MJLY", session_path="/session/mjly", status_text="connected", backend="openvpn3"),
        OpenVpnSession(name="foreign", session_path="/session/foreign", status_text="connected", backend="openvpn3"),
    ]
    manager = OpenVpnManager(ShutdownClassic(), openvpn3)

    result = manager.shutdown([build_profile({"openvpn_backend": "openvpn3"})])

    assert result.success is True
    assert openvpn3.disconnected == ["/session/mjly"]


def test_openvpn_manager_remove_and_logs_use_selected_backend() -> None:
    classic = ClassicManagerStub()
    openvpn3 = OpenVpn3ManagerRecording(True)
    manager = OpenVpnManager(classic, openvpn3)
    profile = build_profile({"openvpn_backend": "openvpn3", "config_path": "/config/ref"})

    removed = manager.remove_profile(profile)
    logs = manager.read_runtime_logs(profile)

    assert removed.success is True
    assert openvpn3.removed == ["/config/ref"]
    assert logs == ["/config/ref"] or logs == ["openvpn3 /config/ref"]


def test_openvpn_manager_helper_normalization_and_backend_fallback(monkeypatch) -> None:
    class UnavailableClassic(ClassicManagerStub):
        def available(self) -> bool:
            return False

    manager = OpenVpnManager(UnavailableClassic(), OpenVpn3ManagerStub(False))
    assert manager._pick_backend("openvpn3") == "openvpn"
    assert manager._config_bool("YES") is True
    assert manager._config_bool("no") is False
    assert manager._config_text("  value ") == "value"
    assert manager._config_text("") is None
