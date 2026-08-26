from kopdes.application.dtos.runtime_state import ActionResult
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.ppp_manager import PppManager
from kopdes.shared.enums import ProtocolType


def build_profile(protocol: ProtocolType) -> ConnectionProfile:
    return ConnectionProfile(
        id="profile-1",
        name="L2TP Branch",
        description="test profile",
        server_address="vpn.example.net",
        protocol=protocol,
        username="operator",
    )


def test_missing_l2tp_plugin_returns_install_hint() -> None:
    manager = PppManager(object())

    result = manager._missing_vpn_plugin(
        ProtocolType.L2TP,
        "Connection activation failed: The VPN service "
        "'org.freedesktop.NetworkManager.l2tp' was not installed.",
    )

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert "L2TP plugin is not installed" in result.message
    assert "network-manager-l2tp" in (result.details or "")


def test_connect_surfaces_missing_l2tp_plugin_from_nmcli(monkeypatch) -> None:
    class Runner:
        def run_privileged(self, command, timeout=30, interactive=False):
            if command[:5] == ["nmcli", "connection", "add", "type", "vpn"]:
                return CommandResult(command, 0, "", "")
            return CommandResult(
                command,
                10,
                "",
                "Connection activation failed: The VPN service "
                "'org.freedesktop.NetworkManager.l2tp' was not installed.",
            )

    monkeypatch.setattr("kopdes.infrastructure.system.ppp_manager.shutil.which", lambda _: "/usr/bin/nmcli")
    result = PppManager(Runner()).connect(build_profile(ProtocolType.L2TP), "secret")

    assert result.success is False
    assert result.message == "NetworkManager L2TP plugin is not installed."
    assert "sudo apt-get install network-manager-l2tp" in (result.details or "")
