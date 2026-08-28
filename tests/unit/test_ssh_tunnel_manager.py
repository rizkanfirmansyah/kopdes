from pathlib import Path

from kopdes.application.dtos.runtime_state import ActionResult
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.system.command_runner import CommandResult
from kopdes.infrastructure.system.ssh_tunnel_manager import SshTunnelManager


class Runner:
    def run_privileged(self, command, timeout=30, interactive=False):
        return CommandResult(command, 0, "", "")


def mapping(mapping_id: str = "mapping-1", local_port: int = 5433) -> PortMapping:
    return PortMapping(
        id=mapping_id,
        name=mapping_id,
        description="PostgreSQL tunnel",
        ssh_host="192.168.0.10",
        ssh_username="boss",
        local_port=local_port,
        remote_host="127.0.0.1",
        remote_port=5432,
    )


def test_build_command_never_contains_password(tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)

    command = manager._build_ssh_command(mapping(), with_password=True)

    assert "boss@192.168.0.10" in command
    assert "-L" in command
    assert "127.0.0.1:5433:127.0.0.1:5432" in command
    assert "secret" not in command
    assert "PubkeyAuthentication=no" in command


def test_start_password_mapping_uses_fd_and_persists_no_secret(tmp_path: Path, monkeypatch) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 43210

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("kopdes.infrastructure.system.ssh_tunnel_manager.subprocess.Popen", fake_popen)
    monkeypatch.setattr(manager, "_local_port_is_busy", lambda _mapping: False)
    monkeypatch.setattr(manager, "_is_local_listener", lambda _mapping: True)

    result = manager.start(mapping(), password="super-secret")

    assert result.success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert "super-secret" not in command
    assert command[0:2] == ["sshpass", "-d"]
    metadata = manager._read_session_metadata("mapping-1")
    assert metadata is not None
    assert "super-secret" not in str(metadata)
    manager._remove_metadata("mapping-1")


def test_start_supports_multiple_distinct_local_forwards(tmp_path: Path, monkeypatch) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    commands: list[list[str]] = []
    next_pid = iter((43211, 43212))

    class FakeProcess:
        def __init__(self, pid: int):
            self.pid = pid

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(command)
        return FakeProcess(next(next_pid))

    monkeypatch.setattr("kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("kopdes.infrastructure.system.ssh_tunnel_manager.subprocess.Popen", fake_popen)
    monkeypatch.setattr(manager, "_local_port_is_busy", lambda _mapping: False)
    monkeypatch.setattr(manager, "_is_local_listener", lambda _mapping: True)

    first = manager.start(mapping("mapping-1", 5433), password=None)
    second = manager.start(mapping("mapping-2", 5434), password=None)

    assert first.success is True
    assert second.success is True
    assert any("127.0.0.1:5433:127.0.0.1:5432" in command for command in commands)
    assert any("127.0.0.1:5434:127.0.0.1:5432" in command for command in commands)
    manager._remove_metadata("mapping-1")
    manager._remove_metadata("mapping-2")


def test_validate_rejects_privileged_local_port(tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)

    error = manager.validate_mapping(mapping(local_port=543), password=None)

    assert error is not None
    assert "1024" in error


def test_ssh_tunnel_manager_trims_runtime_log(tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    manager.MAX_LOG_BYTES = 32
    log_path = tmp_path / "ssh_tunnels" / "runtime" / "mapping-1.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"x" * 100)

    inode = log_path.stat().st_ino
    with log_path.open("ab") as active_writer:
        manager._trim_log(log_path)
        active_writer.write(b"y" * 40 + b"tail")
        active_writer.flush()
        manager._trim_log(log_path)

    assert log_path.stat().st_size <= manager.MAX_LOG_BYTES
    assert log_path.stat().st_ino == inode
    assert log_path.read_bytes().endswith(b"tail")
