from __future__ import annotations

import shlex

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from kopdes.infrastructure.system.command_runner import CommandRunner


class TerminalPanel(QWidget):
    def __init__(self, command_runner: CommandRunner) -> None:
        super().__init__()
        self._command_runner = command_runner
        self._output = QTextEdit()
        self._output.setReadOnly(True)
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
        result = self._command_runner.run(shlex.split(raw), timeout=20)
        self._output.append(f"$ {raw}")
        self._output.append(result.stdout.strip() or result.stderr.strip() or "[no output]")
        self._output.append("")
        self._input.clear()
        self._output.moveCursor(self._output.textCursor().MoveOperation.End)
