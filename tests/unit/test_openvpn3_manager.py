from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.openvpn3_manager import OpenVpn3Manager


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self._stdout = stdout

    def run(self, command, timeout=30):
        return CommandResult(command=command, return_code=0, stdout=self._stdout, stderr="")


def test_openvpn3_manager_parses_configs(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/openvpn3")
    manager = OpenVpn3Manager(
        FakeRunner(
            "Name: VPN-DC1\nConfiguration path: /net/openvpn/v3/configuration/123\nImported: today\n"
        )
    )
    configs = manager.list_configs()
    assert configs[0].name == "VPN-DC1"
    assert configs[0].config_path == "/net/openvpn/v3/configuration/123"
    assert configs[0].backend == "openvpn3"
