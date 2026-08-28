from __future__ import annotations

import shlex

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget

from kopdes.infrastructure.system.command_runner import CommandResult, CommandRunner
from kopdes.ui.operation_controller import OperationController


class TerminalPanel(QWidget):
    MAX_OUTPUT_BLOCKS = 4000

    def __init__(self, command_runner: CommandRunner) -> None:
        super().__init__()
        self._command_runner = command_runner
        self._operations = OperationController(self, max_threads=2)
        self._operation_key = f"terminal:{id(self)}"
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.document().setMaximumBlockCount(self.MAX_OUTPUT_BLOCKS)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Run a diagnostic command, example: ip addr show")
        run_button = QPushButton("Run")
        run_button.clicked.connect(self._run_command)
        self._input.returnPressed.connect(self._run_command)

        row = QHBoxLayout()
        row.addWidget(self._input)
        row.addWidget(run_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._output, stretch=1)
        layout.addLayout(row)

    def _run_command(self) -> None:
        raw = self._input.text().strip()
        if not raw:
            return
        try:
            command = shlex.split(raw)
        except ValueError as exc:
            self._append_output(raw, f"Invalid command syntax: {exc}")
            return
        if not command:
            return
        self._output.append(f"$ {raw}")
        self._output.append("[running]")
        self._input.setEnabled(False)
        submitted = self._operations.submit(
            self._operation_key,
            lambda: self._command_runner.run(command, timeout=20),
            self._command_finished,
            self._command_failed,
        )
        if not submitted:
            self._input.setEnabled(True)
            self._append_output(raw, "Another terminal command is still running.")
            return
        self._output.append("")

    def _command_finished(self, result: object) -> None:
        self._input.setEnabled(True)
        if not isinstance(result, CommandResult):
            self._append_output("", "Command returned an invalid result.")
            return
        output = result.stdout.strip() or result.stderr.strip() or "[no output]"
        self._output.append(output)
        self._output.append("")
        self._input.clear()
        self._output.moveCursor(self._output.textCursor().MoveOperation.End)

    def _command_failed(self, error: Exception) -> None:
        self._input.setEnabled(True)
        self._append_output("", f"Command failed: {error}")

    def _append_output(self, raw: str, message: str) -> None:
        if raw:
            self._output.append(f"$ {raw}")
        self._output.append(message)
        self._output.append("")
        self._output.moveCursor(self._output.textCursor().MoveOperation.End)

    def shutdown(self) -> None:
        self._operations.shutdown()
