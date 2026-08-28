from __future__ import annotations

import logging
import os
import selectors
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from threading import Lock


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute argv commands with bounded output and owned process cleanup."""

    MAX_OUTPUT_BYTES = 256 * 1024
    TERMINATION_GRACE_SECONDS = 0.5

    def __init__(self) -> None:
        self._processes_lock = Lock()
        self._processes: dict[int, subprocess.Popen] = {}

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

    def request_stop_all(self) -> None:
        """Ask only commands started by this runner to stop, without waiting."""
        with self._processes_lock:
            processes = list(self._processes.values())
        for process in processes:
            self._signal_process(process, signal.SIGTERM, process.pid)

    def _execute(self, command: list[str], timeout: int) -> CommandResult:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("Command must be a non-empty argv list.")
        try:
            timeout_seconds = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("Command timeout must be greater than zero.") from exc
        if timeout_seconds <= 0:
            raise ValueError("Command timeout must be greater than zero.")

        safe_command = self._redact_command(command)
        LOGGER.debug("Executing command: %s", shlex.join(safe_command))
        process: subprocess.Popen | None = None
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        stdout_truncated = False
        stderr_truncated = False
        timed_out = False
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                env={**os.environ, "LC_ALL": "C"},
            )
            with self._processes_lock:
                self._processes[process.pid] = process

            streams = ((process.stdout, stdout_buffer), (process.stderr, stderr_buffer))
            with selectors.DefaultSelector() as selector:
                for stream, buffer in streams:
                    if stream is not None:
                        selector.register(stream, selectors.EVENT_READ, buffer)

                deadline = time.monotonic() + timeout_seconds
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        LOGGER.warning(
                            "Command timed out after %s seconds: %s",
                            timeout,
                            command[0],
                        )
                        self._terminate_process(process)
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        try:
                            chunk = os.read(key.fileobj.fileno(), 65536)
                        except OSError:
                            chunk = b""
                        if not chunk:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        buffer = key.data
                        buffer.extend(chunk)
                        if len(buffer) > self.MAX_OUTPUT_BYTES:
                            del buffer[: -self.MAX_OUTPUT_BYTES]
                            if buffer is stdout_buffer:
                                stdout_truncated = True
                            else:
                                stderr_truncated = True

                if timed_out:
                    for key in list(selector.get_map().values()):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()

            if timed_out:
                return_code = 124
            else:
                return_code = process.wait(timeout=1)

            stdout = self._format_output(stdout_buffer, stdout_truncated)
            stderr = self._format_output(stderr_buffer, stderr_truncated)
            if return_code == 124:
                message = f"Command timed out after {timeout} seconds: {command[0]}"
                return CommandResult(safe_command, 124, stdout, stderr or message)
            return CommandResult(
                command=safe_command,
                return_code=return_code,
                stdout=stdout,
                stderr=stderr,
            )
        except FileNotFoundError:
            message = f"Command not found: {command[0]}"
            LOGGER.warning(message)
            return CommandResult(safe_command, 127, "", message)
        except PermissionError:
            LOGGER.warning("Permission denied while executing %s", command[0])
            return CommandResult(safe_command, 126, "", f"Permission denied: {command[0]}")
        except subprocess.TimeoutExpired:
            message = f"Command timed out after {timeout} seconds: {command[0]}"
            LOGGER.warning(message)
            if process is not None:
                self._terminate_process(process)
            return CommandResult(safe_command, 124, "", message)
        except OSError as exc:
            LOGGER.exception("OS error while executing %s", command[0])
            if process is not None:
                self._terminate_process(process)
            return CommandResult(safe_command, 125, "", str(exc))
        finally:
            if process is not None:
                with self._processes_lock:
                    self._processes.pop(process.pid, None)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """Terminate only the process group created for this command."""
        pid = process.pid
        pgid = pid
        if process.poll() is None:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid

        if not self._signal_process(process, signal.SIGTERM, pgid):
            return
        try:
            process.wait(timeout=self.TERMINATION_GRACE_SECONDS)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass

        if not self._signal_process(process, signal.SIGKILL, pgid):
            return
        try:
            process.wait(timeout=self.TERMINATION_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            LOGGER.error("Managed process PID=%s did not exit after KILL", pid)

    def _signal_process(
        self,
        process: subprocess.Popen,
        signum: signal.Signals,
        pgid: int | None = None,
    ) -> bool:
        if process.poll() is not None and pgid is None:
            return True
        pid = process.pid
        if pgid is None:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = None
        try:
            if pgid == pid:
                os.killpg(pgid, signum)
            else:
                process.send_signal(signum)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            return False

    def _format_output(self, output: bytearray, truncated: bool) -> str:
        text = self._decode_output(bytes(output))
        return "[output truncated]\n" + text if truncated else text

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
            lower_item = item.lower()
            if redact_next:
                redacted.append("<redacted>")
                redact_next = False
                continue
            key, separator, _value = lower_item.partition("=")
            if separator and key in sensitive_keys:
                redacted.append(f"{item[:len(key)]}=<redacted>")
                continue
            redacted.append(item)
            if lower_item in sensitive_keys:
                redact_next = True
        return redacted

    def _decode_output(self, output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace")
        return output
