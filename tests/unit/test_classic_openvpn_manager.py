from pathlib import Path

from kopdes.infrastructure.system.classic_openvpn_manager import ClassicOpenVpnManager
from kopdes.infrastructure.system.command_runner import CommandResult


class FakeRunner:
    def __init__(self, return_code: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.commands: list[list[str]] = []
        self.privileged_calls: list[tuple[list[str], bool]] = []

    def run(self, command, timeout=30):
        self.commands.append(command)
        if "--writepid" in command:
            pid_path = Path(command[command.index("--writepid") + 1])
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("99999", encoding="utf-8")
        return CommandResult(command=command, return_code=self.return_code, stdout=self.stdout, stderr=self.stderr)

    def run_privileged(self, command, timeout=30, interactive=False):
        self.privileged_calls.append((command, interactive))
        return self.run(command, timeout=timeout)


def test_classic_openvpn_manager_imports_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    source = tmp_path / "sample.ovpn"
    source.write_text("client\ndev tun9\nremote vpn.example.net 1194\nauth-user-pass\n", encoding="utf-8")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    result = manager.import_config(str(source), "VPN-A")
    assert result.success is True
    assert result.data["openvpn_backend"] == "openvpn"
    assert result.data["interface_name"] == "tun9"
    assert result.data["auth_user_pass_required"] == "true"


def test_classic_openvpn_manager_removes_profile(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    config_path = tmp_path / "openvpn" / "profiles"
    config_path.mkdir(parents=True, exist_ok=True)
    profile = config_path / "vpn-a.ovpn"
    profile.write_text("client\n", encoding="utf-8")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    result = manager.remove_config(str(profile))
    assert result.success is True
    assert profile.exists() is False


def test_classic_openvpn_manager_recovers_pid_from_runtime_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    runtime_dir = tmp_path / "openvpn" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_path = runtime_dir / "mjly.pid"
    pid_path.write_text("4242", encoding="utf-8")
    log_path = runtime_dir / "mjly.log"
    log_path.write_text("Initialization Sequence Completed\n", encoding="utf-8")
    meta_path = runtime_dir / "mjly.json"
    meta_path.write_text(
        """
{
  "name": "Majalaya",
  "config_path": "/tmp/mjly.ovpn",
  "pid": null,
  "pid_path": "%s",
  "log_path": "%s",
  "status_path": "%s",
  "interface_name": "tun0"
}
""".strip()
        % (pid_path, log_path, runtime_dir / "mjly.status"),
        encoding="utf-8",
    )

    sessions = manager.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].pid == 4242
    assert sessions[0].status_text == "connected"


def test_classic_openvpn_manager_ignores_unreadable_status_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    runtime_dir = tmp_path / "openvpn" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_path = runtime_dir / "blocked.pid"
    pid_path.write_text("4242", encoding="utf-8")
    status_path = runtime_dir / "blocked.status"
    status_path.write_text("CONNECTED,SUCCESS\n", encoding="utf-8")
    log_path = runtime_dir / "blocked.log"
    log_path.write_text("", encoding="utf-8")
    meta_path = runtime_dir / "blocked.json"
    meta_path.write_text(
        """
{
  "name": "Blocked",
  "config_path": "/tmp/blocked.ovpn",
  "pid": 4242,
  "pid_path": "%s",
  "log_path": "%s",
  "status_path": "%s",
  "interface_name": "tun0"
}
""".strip()
        % (pid_path, log_path, status_path),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, '_safe_read_text', lambda path: None if path == status_path else '')

    sessions = manager.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].status_text == "running"

def test_classic_openvpn_manager_parses_connecting_runtime_from_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    monkeypatch.setattr(manager, '_pid_looks_like_openvpn', lambda pid: True)
    runtime_dir = tmp_path / "openvpn" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_path = runtime_dir / "connecting.pid"
    pid_path.write_text("4242", encoding="utf-8")
    log_path = runtime_dir / "connecting.log"
    log_path.write_text("TLS: Initial packet from [AF_INET]1.2.3.4:1194\n", encoding="utf-8")
    meta_path = runtime_dir / "connecting.json"
    meta_path.write_text(
        """
{
  "name": "Connecting",
  "config_path": "/tmp/connecting.ovpn",
  "pid": 4242,
  "pid_path": "%s",
  "log_path": "%s",
  "status_path": "%s",
  "interface_name": "tun0"
}
""".strip()
        % (pid_path, log_path, runtime_dir / "connecting.status"),
        encoding="utf-8",
    )

    sessions = manager.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].status_text == "connecting"


def test_classic_openvpn_manager_disconnect_uses_interactive_privilege(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    runner = FakeRunner()
    manager = ClassicOpenVpnManager(runner, tmp_path)
    monkeypatch.setattr(manager, "_pid_looks_like_openvpn", lambda pid: True)
    runtime_dir = tmp_path / "openvpn" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_path = runtime_dir / "majalaya.pid"
    pid_path.write_text("4242", encoding="utf-8")
    meta_path = runtime_dir / "majalaya.json"
    meta_path.write_text(
        """
{
  "name": "Majalaya",
  "config_path": "/tmp/majalaya.ovpn",
  "pid": 4242,
  "pid_path": "%s",
  "log_path": "%s",
  "status_path": "%s",
  "interface_name": "tun0"
}
""".strip()
        % (pid_path, runtime_dir / "majalaya.log", runtime_dir / "majalaya.status"),
        encoding="utf-8",
    )

    result = manager.disconnect_session(str(meta_path))

    assert result.success is True
    assert runner.privileged_calls[-1] == (["kill", "4242"], True)


def test_classic_openvpn_manager_creates_auth_file_for_auth_user_pass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/openvpn")
    runner = FakeRunner()
    manager = ClassicOpenVpnManager(runner, tmp_path)
    ovpn_path = tmp_path / "profile.ovpn"
    ovpn_path.write_text("client\nauth-user-pass\n", encoding="utf-8")

    result = manager.start_session(
        str(ovpn_path),
        "Majalaya",
        username="riezkan",
        password="secret",
        auth_user_pass_required=True,
    )

    assert result.success is True
    command, interactive = runner.privileged_calls[0]
    assert interactive is True
    assert "--auth-user-pass" in command
    auth_path = Path(command[command.index("--auth-user-pass") + 1])
    assert auth_path.exists() is True
    assert auth_path.read_text(encoding="utf-8") == "riezkan\nsecret\n"
    assert (["chmod", "644", str(tmp_path / "openvpn" / "runtime" / "Majalaya.pid")], False) in runner.privileged_calls


def test_classic_openvpn_manager_trims_runtime_log(tmp_path: Path) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    manager.MAX_LOG_BYTES = 32
    log_path = tmp_path / "openvpn" / "runtime" / "session.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"x" * 100)

    inode = log_path.stat().st_ino
    with log_path.open("ab") as active_writer:
        manager._trim_log_file({"log_path": str(log_path)})
        active_writer.write(b"y" * 40 + b"tail")
        active_writer.flush()
        manager._trim_log_file({"log_path": str(log_path)})

    assert log_path.stat().st_size <= manager.MAX_LOG_BYTES
    assert log_path.stat().st_ino == inode
    assert log_path.read_bytes().endswith(b"tail")


def test_classic_openvpn_manager_accepts_verified_root_pid_when_signal_probe_is_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)

    def deny_signal_probe(pid, sig):
        raise PermissionError

    monkeypatch.setattr("os.kill", deny_signal_probe)
    monkeypatch.setattr(manager, "_pid_looks_like_openvpn", lambda _pid: True)
    monkeypatch.setattr(manager, "_process_start_time", lambda _pid: "12345")

    assert manager._pid_running(4242, {"pid_start_time": "12345"}) is True
    assert manager._pid_running(4242, {}) is False

def test_classic_openvpn_polling_does_not_request_privileged_stale_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    runtime_dir = tmp_path / "openvpn" / "runtime"
    meta_path = runtime_dir / "stale.json"
    meta_path.write_text('{"name": "Stale", "pid": 4242}', encoding="utf-8")
    cleanup_calls: list[bool] = []

    monkeypatch.setattr(manager, "_pid_running", lambda _pid, _payload: False)
    monkeypatch.setattr(
        manager,
        "_cleanup_runtime_files",
        lambda _payload, _meta_path, allow_privileged=True: cleanup_calls.append(allow_privileged) or False,
    )

    assert manager.list_sessions() == []
    assert cleanup_calls == [False]
