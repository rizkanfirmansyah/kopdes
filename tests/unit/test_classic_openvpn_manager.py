import json
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


def test_classic_openvpn_reports_unavailable_and_missing_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: None)
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)

    assert manager.available() is False
    assert manager.import_config(str(tmp_path / "missing.ovpn"), "missing").success is False


def test_classic_openvpn_creates_manual_config_with_safe_defaults(tmp_path: Path) -> None:
    from kopdes.domain.entities.connection_profile import ConnectionProfile
    from kopdes.shared.enums import ProtocolType

    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    profile = ConnectionProfile(
        id="manual-1",
        name="Manual VPN",
        description="",
        server_address="vpn.example",
        protocol=ProtocolType.OPENVPN,
        port=443,
        username="operator",
        keepalive=10,
        mtu=1400,
        config_payload={"interface_name": "bad device", "openvpn_proto": "invalid", "auth_user_pass_required": True},
    )

    result = manager.create_manual_config(profile)

    assert result.success is True
    config = Path(result.data["config_path"]).read_text(encoding="utf-8")
    assert "dev tun\n" in config
    assert "proto udp\n" in config
    assert "remote vpn.example 443\n" in config
    assert "auth-user-pass\n" in config
    assert "ping-restart 30\n" in config
    assert "tun-mtu 1400\n" in config
    assert (Path(result.data["config_path"]).stat().st_mode & 0o777) == 0o600


def test_classic_openvpn_rejects_invalid_manual_config_input(tmp_path: Path) -> None:
    from kopdes.domain.entities.connection_profile import ConnectionProfile
    from kopdes.shared.enums import ProtocolType

    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    empty = ConnectionProfile("", "x", "", "", ProtocolType.OPENVPN)
    newline = ConnectionProfile("", "x", "", "vpn\nexample", ProtocolType.OPENVPN)

    assert manager.create_manual_config(empty).success is False
    assert manager.create_manual_config(newline).success is False


def test_classic_openvpn_import_resolves_relative_auth_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: "/usr/bin/openvpn")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    auth = source_dir / "auth.txt"
    auth.write_text("operator\nsecret\n", encoding="utf-8")
    source = source_dir / "profile.ovpn"
    source.write_text("client\nauth-user-pass auth.txt\n", encoding="utf-8")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)

    result = manager.import_config(str(source), "relative-auth")

    assert result.success is True
    assert result.data["auth_user_pass_file"] == str(auth)


def test_classic_openvpn_start_reports_missing_config_and_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: "/usr/bin/openvpn")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)

    assert manager.start_session(str(tmp_path / "missing.ovpn"), "missing").success is False
    config = tmp_path / "profile.ovpn"
    config.write_text("client\n", encoding="utf-8")
    missing_creds = manager.start_session(
        str(config),
        "needs-auth",
        username=None,
        password=None,
        auth_user_pass_required=True,
    )
    missing_file = manager.start_session(
        str(config),
        "missing-file",
        auth_user_pass_file=str(tmp_path / "no-auth"),
    )

    assert "requires username" in missing_creds.message
    assert "credentials file" in missing_file.message


def test_classic_openvpn_start_failure_removes_runtime_auth(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: "/usr/bin/openvpn")
    manager = ClassicOpenVpnManager(FakeRunner(return_code=1, stderr="auth failed"), tmp_path)
    config = tmp_path / "profile.ovpn"
    config.write_text("client\n", encoding="utf-8")

    result = manager.start_session(
        str(config),
        "failed",
        username="operator",
        password="secret",
        auth_user_pass_required=True,
    )

    assert result.success is False
    assert not (tmp_path / "openvpn" / "runtime" / "failed.auth").exists()


def test_classic_openvpn_start_rejects_duplicate_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: "/usr/bin/openvpn")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    config = tmp_path / "profile.ovpn"
    config.write_text("client\n", encoding="utf-8")
    monkeypatch.setattr(manager, "session_path_for_alias", lambda _alias: "/owned/session.json")

    result = manager.start_session(str(config), "duplicate")

    assert result.success is False
    assert "already connected" in result.message


def test_classic_openvpn_start_fails_if_pid_is_not_published(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kopdes.infrastructure.system.classic_openvpn_manager.shutil.which", lambda _name: "/usr/bin/openvpn")
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    config = tmp_path / "profile.ovpn"
    config.write_text("client\n", encoding="utf-8")
    monkeypatch.setattr(manager, "_wait_for_pid", lambda _path: None)
    monkeypatch.setattr(manager, "_find_managed_pid", lambda _config, _alias: None)

    result = manager.start_session(str(config), "no-pid")

    assert result.success is False
    assert "did not publish" in result.message


def test_classic_openvpn_disconnect_validates_path_and_metadata(tmp_path: Path) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    malformed = tmp_path / "openvpn" / "runtime" / "malformed.json"
    malformed.write_text("{bad", encoding="utf-8")
    scalar = tmp_path / "openvpn" / "runtime" / "scalar.json"
    scalar.write_text("[]", encoding="utf-8")

    assert manager.disconnect_session(str(outside)).success is False
    assert manager.disconnect_session(str(malformed)).success is False
    assert manager.disconnect_session(str(scalar)).success is False


def test_classic_openvpn_disconnect_cleans_stale_session(tmp_path: Path, monkeypatch) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    runtime = tmp_path / "openvpn" / "runtime"
    meta = runtime / "stale.json"
    log = runtime / "stale.log"
    status = runtime / "stale.status"
    pid = runtime / "stale.pid"
    for path in (log, status, pid):
        path.write_text("", encoding="utf-8")
    meta.write_text(
        json.dumps(
            {
                "name": "stale",
                "pid": 4242,
                "pid_path": str(pid),
                "log_path": str(log),
                "status_path": str(status),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "_pid_running", lambda _pid, _payload: False)

    result = manager.disconnect_session(str(meta))

    assert result.success is True
    assert not meta.exists()


def test_classic_openvpn_stop_all_reports_disconnect_failure(tmp_path: Path, monkeypatch) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    runtime = tmp_path / "openvpn" / "runtime"
    meta = runtime / "live.json"
    meta.write_text(json.dumps({"name": "live", "pid": 4242}), encoding="utf-8")
    monkeypatch.setattr(manager, "_pid_running", lambda _pid, _payload: True)
    monkeypatch.setattr(manager, "disconnect_session", lambda _path: __import__("kopdes.application.dtos.runtime_state", fromlist=["ActionResult"]).ActionResult(False, "stop failed"))

    result = manager.stop_all_sessions()

    assert result.success is False
    assert "live" in (result.details or "")


def test_classic_openvpn_runtime_helpers_parse_states_and_interfaces(tmp_path: Path) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)

    assert manager._parse_runtime_text("Initialization Sequence Completed\n") == "connected"
    assert manager._parse_runtime_text("AUTH_FAILED\n") == "failed"
    assert manager._parse_runtime_text("Restart pause, 5 second(s)\n") == "reconnecting"
    assert manager._parse_runtime_text("TLS: Initial packet\n") == "connecting"
    assert manager._parse_runtime_text("unrelated\n") is None
    assert manager._read_status_text({"status_path": "", "log_path": ""}) == "running"
    assert manager._resolve_interface_name({"interface_name": "tun9"}) == "tun9"
    assert manager._config_bool("on") is True
    assert manager._config_bool("off") is False


def test_classic_openvpn_read_runtime_logs_bounds_limit(tmp_path: Path, monkeypatch) -> None:
    manager = ClassicOpenVpnManager(FakeRunner(), tmp_path)
    log = tmp_path / "openvpn" / "runtime" / "logs.log"
    log.write_text("\n".join(f"line-{index}" for index in range(5)), encoding="utf-8")
    monkeypatch.setattr(manager, "_runtime_log_path", lambda _alias: log)

    assert manager.read_runtime_logs("logs", 2) == ["line-3", "line-4"]
    assert manager.read_runtime_logs("logs", "bad")[-1] == "line-4"
