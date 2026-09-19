from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.ppp_manager import PppManager
from kopdes.shared.enums import ProtocolType


class Runner:
    def __init__(self):
        self.privileged_calls = []

    def run_privileged(self, command, timeout=30, interactive=False):
        self.privileged_calls.append((command, interactive))
        return CommandResult(command, 0, "", "")


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


def generic_profile(profile_id: str = "profile-ppp") -> ConnectionProfile:
    return ConnectionProfile(
        id=profile_id,
        name="Generic PPP",
        description="test profile",
        server_address="",
        protocol=ProtocolType.PPP,
        username="operator",
        config_payload={"peer_name": "secure-peer"},
    )


def test_generic_ppp_disconnect_without_metadata_never_uses_poff(tmp_path: Path) -> None:
    class RecordingRunner(Runner):
        def __init__(self):
            self.calls = []

        def run_privileged(self, command, timeout=30, interactive=False):
            self.calls.append(command)
            return CommandResult(command, 0, "", "")

    runner = RecordingRunner()
    result = PppManager(runner, tmp_path).disconnect(generic_profile())

    assert result.success is True
    assert "not managed" in result.message
    assert runner.calls == []


def test_generic_ppp_refuses_pid_that_is_not_owned(tmp_path: Path, monkeypatch) -> None:
    runner = Runner()
    manager = PppManager(runner, tmp_path)
    metadata = {
        "profile_id": "profile-ppp",
        "name": "Generic PPP",
        "protocol": "ppp",
        "peer": "secure-peer",
        "linkname": "kopdes-profile-ppp",
        "pid": 4242,
        "pid_start_time": "100",
        "state": "RUNNING",
    }
    manager._write_metadata("profile-ppp", metadata)
    monkeypatch.setattr(manager, "_pid_exists", lambda _pid: True)
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: False)

    result = manager.disconnect(generic_profile())

    assert result.success is False
    assert "ownership" in result.message
    assert runner.privileged_calls == []
    stored = manager._read_metadata("profile-ppp")
    assert stored is not None
    assert stored["state"] == "FAILED"


def test_generic_ppp_process_exit_is_marked_failed_without_killing_anything(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = PppManager(Runner(), tmp_path)
    manager._write_metadata(
        "profile-ppp",
        {
            "profile_id": "profile-ppp",
            "name": "Generic PPP",
            "protocol": "ppp",
            "linkname": "kopdes-profile-ppp",
            "pid": 4242,
            "pid_start_time": "100",
            "state": "RUNNING",
        },
    )
    monkeypatch.setattr("kopdes.infrastructure.system.ppp_manager.shutil.which", lambda _name: None)
    monkeypatch.setattr(manager, "_pid_exists", lambda _pid: False)
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: False)

    assert manager.list_active_connections() == {}
    stored = manager._read_metadata("profile-ppp")
    assert stored is not None
    assert stored["state"] == "FAILED"
    assert "exited" in stored["last_error"]


def test_generic_ppp_disconnect_terminates_only_owned_process(tmp_path: Path, monkeypatch) -> None:
    runner = Runner()
    manager = PppManager(runner, tmp_path)
    pid_file = tmp_path / "ppp-owned.pid"
    manager._pid_paths = lambda _link: (pid_file,)
    manager._write_metadata(
        "profile-ppp",
        {
            "profile_id": "profile-ppp",
            "name": "Generic PPP",
            "protocol": "ppp",
            "peer": "secure-peer",
            "linkname": "kopdes-profile-ppp",
            "pid": 4242,
            "pid_path": str(pid_file),
            "pid_start_time": "100",
            "state": "RUNNING",
        },
    )
    pid_exists = iter((True, False))
    monkeypatch.setattr(manager, "_pid_exists", lambda _pid: next(pid_exists))
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: True)
    monkeypatch.setattr("os.getpgid", lambda _pid: 4242)
    monkeypatch.setattr("os.killpg", lambda _pgid, _signal: None)

    result = manager.disconnect(generic_profile())

    assert result.success is True
    assert not manager._metadata_path("profile-ppp").exists()
    assert not pid_file.exists()
    assert runner.privileged_calls == []


def test_generic_ppp_requires_pid_file_after_start(monkeypatch, tmp_path: Path) -> None:
    runner = Runner()
    manager = PppManager(runner, tmp_path)
    monkeypatch.setattr("kopdes.infrastructure.system.ppp_manager.shutil.which", lambda _name: "/usr/sbin/pppd")
    monkeypatch.setattr(manager, "_wait_for_pid", lambda _link: None)

    result = manager.connect(generic_profile(), "secret")

    assert result.success is False
    assert "ownership PID" in result.message
    assert list(manager._runtime_dir.glob("*.tmp")) == []
