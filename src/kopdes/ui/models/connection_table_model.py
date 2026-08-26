from __future__ import annotations

import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from kopdes.application.dtos.runtime_state import ConnectionRow
from kopdes.shared.enums import ConnectionStatus


class ConnectionTableModel(QAbstractTableModel):
    HEADERS = [
        "Status",
        "Connection",
        "Backend",
        "Tunnel",
        "Latency",
        "Upload",
        "Download",
        "Trend",
        "Duration",
        "Error",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ConnectionRow] = []

    def set_rows(self, rows: list[ConnectionRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                self._format_status(row),
                f"{row.name}\n{row.protocol} | {row.server}",
                row.backend,
                f"{row.interface_name}\n{row.local_ip}",
                f"{row.latency_ms:.2f} ms" if row.latency_ms is not None else row.packet_loss,
                self._format_rate(row.tx_rate_bps),
                self._format_rate(row.rx_rate_bps),
                "",
                row.duration_text,
                row.last_error,
            ]
            return values[column]
        if role == Qt.ItemDataRole.UserRole:
            return row.profile_id
        if role == Qt.ItemDataRole.UserRole + 1:
            return row.upload_history
        if role == Qt.ItemDataRole.UserRole + 2:
            return row.download_history
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            if row.status == ConnectionStatus.ACTIVE:
                return QColor("#3be38c")
            if row.status == ConnectionStatus.FAILED:
                return QColor("#ff6b6b")
            if row.status == ConnectionStatus.DEGRADED:
                return QColor("#ffb84d")
            if row.status == ConnectionStatus.RECONNECTING:
                return QColor("#7aa2ff")
            if row.status == ConnectionStatus.CONNECTING:
                return QColor("#5cc8ff")
            return QColor("#9ab2c7")
        return None

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def profile_id_at(self, row_index: int) -> str | None:
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index].profile_id
        return None

    def _format_status(self, row: ConnectionRow) -> str:
        label = row.status.value.upper()
        if row.status in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING}:
            dots = "." * (1 + (int(time.time()) % 3))
            return f"{label}{dots}"
        return label

    def _format_rate(self, value: float) -> str:
        return f"{self._format_bytes(int(value))}/s"

    def _format_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
