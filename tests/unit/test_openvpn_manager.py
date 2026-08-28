from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult
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
