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
        self._status_overrides: dict[str, ConnectionStatus] = {}

    def set_rows(self, rows: list[ConnectionRow]) -> None:
        previous_ids = [row.profile_id for row in self._rows]
        current_ids = [row.profile_id for row in rows]
        self._status_overrides = {
            profile_id: status
            for profile_id, status in self._status_overrides.items()
            if profile_id in current_ids
        }
        if previous_ids == current_ids:
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(self.HEADERS) - 1), [])
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_status_override(self, profile_id: str, status: ConnectionStatus) -> None:
        self._status_overrides[profile_id] = status
        for row, item in enumerate(self._rows):
            if item.profile_id == profile_id:
                self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [])
                return

    def clear_status_override(self, profile_id: str) -> None:
        if profile_id not in self._status_overrides:
            return
        self._status_overrides.pop(profile_id, None)
        for row, item in enumerate(self._rows):
            if item.profile_id == profile_id:
                self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [])
                return

    def status_for(self, profile_id: str) -> ConnectionStatus | None:
        for row in self._rows:
            if row.profile_id == profile_id:
                return self._status_overrides.get(profile_id, row.status)
        return None

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
        status = self._status_overrides.get(row.profile_id, row.status)
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                self._format_status(status),
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
            colors = {
                ConnectionStatus.ACTIVE: "#3be38c",
                ConnectionStatus.FAILED: "#ff6b6b",
                ConnectionStatus.DEGRADED: "#ffb84d",
                ConnectionStatus.RECONNECTING: "#7aa2ff",
                ConnectionStatus.CONNECTING: "#5cc8ff",
                ConnectionStatus.DISCONNECTING: "#5cc8ff",
            }
            return QColor(colors.get(status, "#9ab2c7"))
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

    def _format_status(self, status: ConnectionStatus) -> str:
        label = {
            ConnectionStatus.ACTIVE: "CONNECTED",
            ConnectionStatus.INACTIVE: "DISCONNECTED",
            ConnectionStatus.DISCONNECTING: "DISCONNECTING",
            ConnectionStatus.FAILED: "FAILED",
            ConnectionStatus.DEGRADED: "DEGRADED",
            ConnectionStatus.RECONNECTING: "RECONNECTING",
            ConnectionStatus.CONNECTING: "CONNECTING",
        }.get(status, "UNKNOWN")
        if status in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING, ConnectionStatus.DISCONNECTING}:
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
