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


class OpenVpn3ScenarioRunner:
    def __init__(self, results: dict[str, CommandResult]) -> None:
        self.results = results
        self.calls: list[list[str]] = []

    def run(self, command, timeout=30):
        del timeout
        self.calls.append(command)
        for prefix, result in self.results.items():
            if " ".join(command[: len(prefix.split())]) == prefix:
                return CommandResult(command, result.return_code, result.stdout, result.stderr)
        return CommandResult(command, 0, "", "")


def test_openvpn3_capability_unavailable_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.openvpn3_manager.shutil.which", lambda _name: None)
    manager = OpenVpn3Manager(FakeRunner(""))

    assert manager.available() is False
    assert manager.import_config("/tmp/missing.ovpn", "missing").success is False
    assert manager.start_session("missing").success is False
    assert manager.disconnect_session("/session/missing").success is False
    assert manager.remove_config("missing").success is False
    assert manager.list_configs() == []
    assert manager.list_sessions() == []
    assert manager.read_runtime_logs("missing") == []


def test_openvpn3_reports_command_failures(monkeypatch) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.openvpn3_manager.shutil.which", lambda _name: "/usr/bin/openvpn3")

    class FailingRunner:
        def run(self, command, timeout=30):
            return CommandResult(command, 7, "", "synthetic backend error")

    manager = OpenVpn3Manager(FailingRunner())

    assert manager.import_config("x.ovpn", "x").message == "OpenVPN3 import failed."
    assert manager.list_configs() == []
    assert manager.list_sessions() == []
    assert manager.start_session("x").message == "OpenVPN3 session start failed."
    assert manager.disconnect_session("/session/x").message == "OpenVPN3 disconnect failed."
    assert manager.remove_config("x").message == "OpenVPN3 config removal failed."


def test_openvpn3_parses_sessions_and_skips_incomplete_blocks(monkeypatch) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.openvpn3_manager.shutil.which", lambda _name: "/usr/bin/openvpn3")
    output = (
        "Path: /session/one\nConfig name: VPN-ONE\nStatus: Connected\n"
        "Configuration path: /config/one\n\n"
        "Name: incomplete\n\n"
        "Path: /session/two\nName: VPN-TWO\nStatus: Reconnecting\nConfig path: /config/two\n"
    )
    manager = OpenVpn3Manager(FakeRunner(output))

    sessions = manager.list_sessions()

    assert [session.name for session in sessions] == ["VPN-ONE", "VPN-TWO"]
    assert sessions[1].status_text == "Reconnecting"
    assert sessions[1].config_path == "/config/two"


def test_openvpn3_import_and_listing_use_cli_contract(monkeypatch) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.openvpn3_manager.shutil.which", lambda _name: "/usr/bin/openvpn3")
    runner = OpenVpn3ScenarioRunner(
        {
            "openvpn3 config-import": CommandResult([], 0, "Configuration path: /config/one\n", ""),
            "openvpn3 configs-list": CommandResult(
                [],
                0,
                "Name: VPN-ONE\nConfiguration path: /config/one\nImported: today\n",
                "",
            ),
        }
    )
    manager = OpenVpn3Manager(runner)

    imported = manager.import_config("one.ovpn", "VPN-ONE")
    configs = manager.list_configs()

    assert imported.success is True
    assert imported.data["config_path"] == "/config/one"
    assert configs[0].imported_at == "today"
    assert runner.calls[0] == [
        "openvpn3",
        "config-import",
        "--config",
        "one.ovpn",
        "--name",
        "VPN-ONE",
        "--persistent",
    ]
