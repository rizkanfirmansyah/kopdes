from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatusCard(QFrame):
    def __init__(self, title: str, value: str = "-", accent: str = "#1f8a70") -> None:
        super().__init__()
        self._value_label = QLabel(value)
        self._value_label.setObjectName("statusCardValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title_label = QLabel(title)
        title_label.setObjectName("statusCardTitle")
        layout = QVBoxLayout(self)
        layout.addWidget(title_label)
        layout.addWidget(self._value_label)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: #14202b;
                border: 1px solid #22384d;
                border-left: 4px solid {accent};
                border-radius: 10px;
                padding: 8px;
            }}
            QLabel#statusCardTitle {{
                color: #7ba6c8;
                font-size: 12px;
            }}
            QLabel#statusCardValue {{
                color: #e8f1f7;
                font-size: 24px;
                font-weight: 700;
            }}
            """
        )

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)
