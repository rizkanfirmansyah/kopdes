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
    """Execute argv commands without allowing transient system errors to crash the UI."""

    def run(self, command: list[str], timeout: int = 30) -> CommandResult:
        return self._execute(command, timeout)

    def run_privileged(
        self,
        command: list[str],
        timeout: int = 30,
        interactive: bool = False,
    ) -> CommandResult:
        privileged = self._build_privileged_command(command, interactive)
        return self._execute(privileged, timeout)

    def _execute(self, command: list[str], timeout: int) -> CommandResult:
        if not command or any(not item for item in command):
            raise ValueError("Command must be a non-empty argv list.")
        LOGGER.debug("Executing command: %s", shlex.join(self._redact_command(command)))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            message = f"Command not found: {command[0]}"
            LOGGER.warning(message)
            return CommandResult(command, 127, "", message)
        except PermissionError as exc:
            LOGGER.warning("Permission denied while executing %s: %s", command[0], exc)
            return CommandResult(command, 126, "", f"Permission denied: {command[0]}")
        except subprocess.TimeoutExpired as exc:
            message = f"Command timed out after {timeout} seconds: {command[0]}"
            LOGGER.warning(message)
            stdout = self._decode_output(exc.stdout)
            stderr = self._decode_output(exc.stderr)
            return CommandResult(command, 124, stdout, stderr or message)
        except OSError as exc:
            LOGGER.exception("OS error while executing %s", command[0])
            return CommandResult(command, 125, "", str(exc))

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

    def _redact_command(self, command: list[str]) -> list[str]:
        redacted: list[str] = []
        redact_next = False
        sensitive_keys = {
            "password",
            "passwd",
            "secret",
            "vpn.secrets",
            "ipsec-psk",
        }
        for item in command:
            if redact_next:
                redacted.append("<redacted>")
                redact_next = False
                continue
            redacted.append(item)
            if item.lower() in sensitive_keys:
                redact_next = True
        return redacted

    def _decode_output(self, output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output
