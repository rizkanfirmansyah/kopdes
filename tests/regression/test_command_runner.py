import os

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
