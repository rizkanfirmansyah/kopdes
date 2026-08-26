from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class LogViewer(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)

    def replace_entries(self, messages: list[str]) -> None:
        self.setPlainText("\n".join(messages))
