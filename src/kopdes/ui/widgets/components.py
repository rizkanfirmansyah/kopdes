from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from kopdes.shared.enums import ConnectionStatus


class StatusBadge(QLabel):
    _labels = {
        "active": "CONNECTED",
        "inactive": "DISCONNECTED",
        "connecting": "CONNECTING",
        "disconnecting": "DISCONNECTING",
        "reconnecting": "RECONNECTING",
        "failed": "FAILED",
        "degraded": "DEGRADED",
        "unknown": "UNKNOWN",
    }

    def __init__(self, status: ConnectionStatus | str = "unknown", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: ConnectionStatus | str) -> None:
        normalized = str(status.value if isinstance(status, ConnectionStatus) else status).strip().lower()
        normalized = normalized.replace("_", "-")
        state = normalized or "unknown"
        self.setProperty("state", state)
        self.setText(self._labels.get(state, state.upper()))
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "-", accent: str = "#55d7ed", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self._value = QLabel(value)
        self._value.setObjectName("metricValue")
        self._title = QLabel(title.upper())
        self._title.setObjectName("metricTitle")
        self._meta = QLabel("")
        self._meta.setObjectName("metricMeta")
        self._meta.setVisible(False)
        self.setProperty("accent", accent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._meta)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_meta(self, value: str) -> None:
        self._meta.setText(value)
        self._meta.setVisible(bool(value))


class DetailPanel(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        if title:
            heading = QLabel(title)
            heading.setObjectName("panelTitle")
            layout.addWidget(heading)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setObjectName("panelSubtitle")
            caption.setWordWrap(True)
            layout.addWidget(caption)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        layout.addLayout(self.body, 1)


class ActionButton(QPushButton):
    def __init__(self, text: str, variant: str = "secondary", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("actionButton")
        self.setProperty("variant", variant)


class EmptyState(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("emptyState")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)


class LoadingState(EmptyState):
    def __init__(self, text: str = "Loading...", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("loadingState")


class ErrorState(EmptyState):
    def __init__(self, text: str = "Unable to load this view.", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("errorState")


class ConfirmationDialog:
    @staticmethod
    def ask(parent: QWidget, title: str, text: str, details: Iterable[str] = ()) -> bool:
        message = QMessageBox(parent)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle(title)
        message.setText(text)
        detail_text = "\n".join(item for item in details if item)
        if detail_text:
            message.setDetailedText(detail_text)
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.No)
        return message.exec() == QMessageBox.StandardButton.Yes
