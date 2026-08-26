from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, command: list[str], timeout: int = 30) -> CommandResult:
        return self._execute(command, timeout)

    def run_privileged(self, command: list[str], timeout: int = 30, interactive: bool = False) -> CommandResult:
        privileged = self._build_privileged_command(command, interactive)
        return self._execute(privileged, timeout)

    def _execute(self, command: list[str], timeout: int) -> CommandResult:
        if not command or any(not item for item in command):
            raise ValueError("Command must be a non-empty argv list.")
        LOGGER.debug("Executing command: %s", shlex.join(command))
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            command=command,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _build_privileged_command(self, command: list[str], interactive: bool) -> list[str]:
        if os.geteuid() == 0:
            return command
        if interactive and shutil.which("pkexec"):
            return ["pkexec", *command]
        if shutil.which("sudo"):
            return ["sudo", "-n", *command]
        return command
