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


def test_ssh_start_rejects_missing_clients_and_busy_port(monkeypatch, tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    monkeypatch.setattr("kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which", lambda _name: None)
    missing = manager.start(mapping(), password=None)
    assert "OpenSSH" in missing.message

    monkeypatch.setattr(
        "kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which",
        lambda name: "/usr/bin/ssh" if name == "ssh" else None,
    )
    no_sshpass = manager.start(mapping(), password="secret")
    assert "sshpass" in (no_sshpass.details or "")

    monkeypatch.setattr(
        "kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which",
        lambda _name: "/usr/bin/tool",
    )
    monkeypatch.setattr(manager, "_local_port_is_busy", lambda _mapping: True)
    busy = manager.start(mapping(), password=None)
    assert busy.success is False
    assert "already in use" in busy.message


def test_ssh_start_reports_immediate_process_exit(monkeypatch, tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)

    class Exited:
        pid = 43100

        def poll(self):
            return 255

    monkeypatch.setattr(
        "kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which",
        lambda _name: "/usr/bin/tool",
    )
    monkeypatch.setattr(
        "kopdes.infrastructure.system.ssh_tunnel_manager.subprocess.Popen",
        lambda _command, **_kwargs: Exited(),
    )
    monkeypatch.setattr(manager, "_local_port_is_busy", lambda _mapping: False)
    result = manager.start(mapping(), password=None)

    assert result.success is False
    assert "exited before" in result.message
    assert manager._read_session_metadata("mapping-1") is None


def test_ssh_start_handles_process_creation_errors(monkeypatch, tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    monkeypatch.setattr(
        "kopdes.infrastructure.system.ssh_tunnel_manager.shutil.which",
        lambda _name: "/usr/bin/tool",
    )
    monkeypatch.setattr(manager, "_local_port_is_busy", lambda _mapping: False)

    for error, name in (
        (FileNotFoundError("ssh missing"), "error-file"),
        (PermissionError("denied"), "error-permission"),
        (OSError("broken pipe"), "error-os"),
    ):
        monkeypatch.setattr(
            "kopdes.infrastructure.system.ssh_tunnel_manager.subprocess.Popen",
            lambda _command, error=error, **_kwargs: (_ for _ in ()).throw(error),
        )
        result = manager.start(mapping(name), password=None)
        assert result.success is False


def test_ssh_start_reuses_owned_metadata(monkeypatch, tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    manager._write_metadata(
        "mapping-1",
        {
            "mapping_id": "mapping-1",
            "name": "mapping-1",
            "pid": 43101,
            "local_host": "127.0.0.1",
            "local_port": 5433,
        },
    )
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: True)
    monkeypatch.setattr(manager, "_is_local_listener", lambda _mapping: True)
    result = manager.start(mapping(), password=None)

    assert result.success is True
    assert "already running" in result.message


def test_ssh_list_sessions_handles_valid_stale_and_startup_timeout(tmp_path: Path, monkeypatch) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    manager._write_metadata(
        "valid",
        {
            "mapping_id": "valid",
            "name": "valid",
            "pid": 43102,
            "ssh_host": "192.0.2.1",
            "ssh_username": "boss",
            "local_host": "127.0.0.1",
            "local_port": 5433,
            "remote_host": "127.0.0.1",
            "remote_port": 5432,
            "pid_start_time": "100",
        },
    )
    manager._write_metadata("stale", {"mapping_id": "stale", "pid": 43103})
    manager._write_metadata(
        "timed",
        {
            "mapping_id": "timed",
            "name": "timed",
            "pid": 43104,
            "local_host": "127.0.0.1",
            "local_port": 5434,
            "remote_host": "127.0.0.1",
            "remote_port": 5432,
            "pid_start_time": "100",
        },
    )
    monkeypatch.setattr(manager, "_pid_matches", lambda pid, _metadata: pid == 43102 or pid == 43104)
    monkeypatch.setattr(manager, "_is_local_listener_values", lambda _host, port: port == 5433)
    monkeypatch.setattr(manager, "_startup_timed_out", lambda _metadata, path: path.stem == "timed")
    terminated: list[int] = []
    monkeypatch.setattr(manager, "_terminate_pid", lambda pid: terminated.append(pid) or True)

    sessions = manager.list_sessions()

    assert [session.mapping_id for session in sessions] == ["valid"]
    assert sessions[0].status_text == "active"
    assert terminated == [43104]
    assert manager._read_session_metadata("stale") is None


def test_ssh_stop_cleans_missing_stale_and_owned_sessions(tmp_path: Path, monkeypatch) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    assert manager.stop("").success is False
    assert manager.stop("missing").success is True

    manager._write_metadata("stale", {"mapping_id": "stale", "pid": 43105})
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: False)
    stale = manager.stop("stale")
    assert stale.success is True

    manager._write_metadata(
        "owned",
        {
            "mapping_id": "owned",
            "pid": 43106,
            "pid_start_time": "100",
            "ssh_host": "192.0.2.1",
            "ssh_username": "boss",
            "local_host": "127.0.0.1",
            "local_port": 5433,
            "remote_host": "127.0.0.1",
            "remote_port": 5432,
        },
    )
    class Process:
        def wait(self, timeout=0.5):
            return 0

    manager._processes["owned"] = Process()
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: True)
    monkeypatch.setattr(manager, "_terminate_pid", lambda _pid: True)
    owned = manager.stop("owned")
    assert owned.success is True
    assert manager._read_session_metadata("owned") is None


def test_ssh_stop_all_and_request_stop_are_bounded(tmp_path: Path, monkeypatch) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    invalid = tmp_path / "ssh_tunnels" / "runtime" / "invalid.json"
    invalid.write_text("{bad", encoding="utf-8")
    manager._write_metadata("one", {"mapping_id": "one", "pid": 43107})
    monkeypatch.setattr(manager, "stop", lambda mapping_id: ActionResult(False, f"failed {mapping_id}"))
    failed = manager.stop_all()
    assert failed.success is False

    class Process:
        pid = 43108

    manager._processes["one"] = Process()
    stopped: list[int] = []
    monkeypatch.setattr(manager, "_request_stop_pid", lambda pid: stopped.append(pid))
    manager.request_stop_all()
    assert stopped == [43108]
    assert manager.shutdown([]).success is False


def test_ssh_validation_and_network_probes_cover_invalid_inputs(tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    invalid = mapping()
    invalid.ssh_host = ""
    assert "required" in (manager.validate_mapping(invalid) or "")
    invalid = mapping()
    invalid.local_port = 70000
    assert "65535" in (manager.validate_mapping(invalid) or "")
    invalid = mapping()
    invalid.ssh_username = "bad user"
    assert "whitespace" in (manager.validate_mapping(invalid) or "")
    invalid = mapping()
    invalid.identity_file = str(tmp_path / "missing.key")
    assert "does not exist" in (manager.validate_mapping(invalid) or "")
    assert manager.validate_mapping(mapping(), password="\x00") is not None
    assert manager._is_local_listener_values("127.0.0.1", None) is False
    assert manager._as_pid("bad") is None
    assert manager._as_pid(1) is None
    assert manager._as_port("bad") is None
    assert manager._as_port(70000) is None


def test_ssh_helpers_bound_logs_and_reject_external_paths(tmp_path: Path) -> None:
    manager = SshTunnelManager(Runner(), tmp_path)
    log = tmp_path / "ssh_tunnels" / "runtime" / "tail.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert manager._read_log_tail(log, 2) == "two\nthree"
    assert manager._read_log_tail(tmp_path / "missing") == ""
    manager.MAX_LOG_BYTES = 4
    manager._trim_log(log)
    manager._trim_log(tmp_path / "outside.log")
    assert manager._startup_timed_out({"started_at": "bad"}, log) is False
    assert manager._is_within(log, manager._runtime_dir) is True
