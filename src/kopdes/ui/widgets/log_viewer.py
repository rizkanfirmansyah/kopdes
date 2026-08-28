from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class LogViewer(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self._last_entries: tuple[str, ...] = ()
        self.setReadOnly(True)

    def replace_entries(self, messages: list[str]) -> None:
        entries = tuple(messages)
        if entries == self._last_entries:
            return
        self._last_entries = entries
        self.setPlainText("\n".join(messages))
