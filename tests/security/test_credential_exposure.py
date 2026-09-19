from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.system.command_runner import CommandRunner, CommandResult
from kopdes.infrastructure.system.ppp_manager import PppManager
from kopdes.shared.enums import ProtocolType


TEST_PASSWORD = "TEST_SECRET_123456"
TEST_PSK = "TEST_PSK_789"


class CaptureRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.private_files: list[tuple[str, int, str]] = []

    def run_privileged(self, command, timeout=30, interactive=False, redact_values=()):
        del timeout, interactive, redact_values
        self.calls.append(list(command))
        if command[:5] == ["nmcli", "connection", "add", "type", "vpn"]:
            return CommandResult(list(command), 0, "", "")
        if command[:2] == ["nmcli", "connection"] and "passwd-file" in command:
            path = Path(command[command.index("passwd-file") + 1])
            self.private_files.append(
                (
                    str(path),
                    stat.S_IMODE(path.stat().st_mode),
                    path.read_text(encoding="utf-8"),
                )
            )
            return CommandResult(list(command), 0, "", f"{TEST_PASSWORD} {TEST_PSK}")
        if command and command[0] == "pppd":
            path = Path(command[command.index("file") + 1])
            self.private_files.append(
                (
                    str(path),
                    stat.S_IMODE(path.stat().st_mode),
                    path.read_text(encoding="utf-8"),
                )
            )
            return CommandResult(list(command), 0, "", TEST_PASSWORD)
        return CommandResult(list(command), 0, "", "")


def profile(protocol: ProtocolType, profile_id: str = "profile-1", **payload) -> ConnectionProfile:
    return ConnectionProfile(
        id=profile_id,
        name="Secure PPP",
        description="test",
        server_address="vpn.example",
        protocol=protocol,
        username="operator",
        config_payload=payload,
    )


def test_nmcli_uses_private_password_file_and_never_argv_secret(monkeypatch, tmp_path: Path) -> None:
    runner = CaptureRunner()
    manager = PppManager(runner, tmp_path)
    monkeypatch.setattr("kopdes.infrastructure.system.ppp_manager.shutil.which", lambda _: "/usr/bin/nmcli")

    result = manager.connect(
        profile(ProtocolType.L2TP_IPSEC, ipsec_psk=TEST_PSK),
        TEST_PASSWORD,
    )

    assert result.success is True
    assert all(TEST_PASSWORD not in argument and TEST_PSK not in argument for call in runner.calls for argument in call)
    assert runner.private_files == [
        (
            runner.private_files[0][0],
            0o600,
            f"vpn.secrets.password:{TEST_PASSWORD}\nvpn.secrets.ipsec-psk:{TEST_PSK}\n",
        )
    ]
    assert not Path(runner.private_files[0][0]).exists()
    assert TEST_PASSWORD not in (result.details or "")
    assert TEST_PSK not in (result.details or "")


def test_pppd_uses_private_options_file_and_persists_no_secret(monkeypatch, tmp_path: Path) -> None:
    runner = CaptureRunner()
    manager = PppManager(runner, tmp_path)
    monkeypatch.setattr("kopdes.infrastructure.system.ppp_manager.shutil.which", lambda _: "/usr/sbin/pppd")
    monkeypatch.setattr(manager, "_wait_for_pid", lambda _link: (4242, Path("/run/ppp-kopdes-profile-1.pid")))
    monkeypatch.setattr(manager, "_process_start_time", lambda _pid: "12345")
    monkeypatch.setattr(manager, "_pid_matches", lambda _pid, _metadata: True)

    result = manager.connect(profile(ProtocolType.PPP, peer_name="secure-peer"), TEST_PASSWORD)

    assert result.success is True
    command = runner.calls[0]
    assert TEST_PASSWORD not in command
    assert "password" not in command
    assert "file" in command
    path, mode, content = runner.private_files[0]
    assert mode == 0o600
    assert content == f"user operator\npassword {TEST_PASSWORD}\n"
    assert not Path(path).exists()
    metadata = manager._read_metadata("profile-1")
    assert metadata is not None
    assert TEST_PASSWORD not in str(metadata)


def test_command_runner_redacts_secret_output_and_command_metadata() -> None:
    runner = CommandRunner()
    result = runner.run(
        [sys.executable, "-c", f"print({TEST_PASSWORD!r})"],
        redact_values=[TEST_PASSWORD],
    )

    assert TEST_PASSWORD not in result.stdout
    assert TEST_PASSWORD not in result.stderr
    assert all(TEST_PASSWORD not in argument for argument in result.command)
