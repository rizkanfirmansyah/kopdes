import os
import sys
import threading
import time

import pytest

from kopdes.infrastructure.system.command_runner import CommandRunner


def test_command_runner_rejects_empty_commands() -> None:
    runner = CommandRunner()
    with pytest.raises(ValueError):
        runner.run([])


def test_command_runner_prefers_pkexec_for_interactive_privileged_commands(monkeypatch) -> None:
    runner = CommandRunner()
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/pkexec' if name == 'pkexec' else '/usr/bin/sudo')

    command = runner._build_privileged_command(['openvpn', '--config', 'vpn.ovpn'], interactive=True)

    assert command[:2] == ['pkexec', 'openvpn']


def test_command_runner_falls_back_to_sudo_for_noninteractive_privileged_commands(monkeypatch) -> None:
    runner = CommandRunner()
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    monkeypatch.setattr('shutil.which', lambda name: None if name == 'pkexec' else '/usr/bin/sudo')

    command = runner._build_privileged_command(['kill', '1234'], interactive=False)

    assert command[:3] == ['sudo', '-n', 'kill']



def test_command_runner_timeout_terminates_descendants(tmp_path) -> None:
    runner = CommandRunner()
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    result = runner.run([sys.executable, "-c", script, str(child_pid_file)], timeout=0.2)

    assert result.return_code == 124
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant PID {child_pid} survived command timeout")


def test_command_runner_bounds_output_and_redacts_inline_secrets() -> None:
    runner = CommandRunner()
    runner.MAX_OUTPUT_BYTES = 32
    result = runner.run([sys.executable, "-c", "print('x' * 100)"])

    assert result.return_code == 0
    assert "output truncated" in result.stdout
    assert len(result.stdout) <= 64
    assert runner._redact_command(["nmcli", "vpn.secrets", "password=secret"]) == [
        "nmcli",
        "vpn.secrets",
        "<redacted>",
    ]
    assert runner._redact_command(["nmcli", "password=secret", "ipsec-psk=hidden"]) == [
        "nmcli",
        "password=<redacted>",
        "ipsec-psk=<redacted>",
    ]

def test_command_runner_request_stop_all_interrupts_active_command() -> None:
    runner = CommandRunner()
    result_holder = {}
    worker = threading.Thread(
        target=lambda: result_holder.setdefault(
            "result",
            runner.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=30),
        )
    )
    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not runner._processes:
        time.sleep(0.01)

    runner.request_stop_all()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result_holder["result"].return_code != 0


def test_command_runner_timeout_kills_descendant_after_parent_exit(tmp_path) -> None:
    runner = CommandRunner()
    child_pid_file = tmp_path / "child-after-parent.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
    )
    result = runner.run([sys.executable, "-c", script, str(child_pid_file)], timeout=0.2)

    assert result.return_code == 124
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant PID {child_pid} survived parent-exit timeout")
