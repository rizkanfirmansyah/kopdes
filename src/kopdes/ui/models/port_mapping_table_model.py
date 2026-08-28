from __future__ import annotations

import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from kopdes.application.dtos.runtime_state import PortMappingRow
from kopdes.shared.enums import ConnectionStatus


class PortMappingTableModel(QAbstractTableModel):
    HEADERS = ["Status", "Mapping", "Local", "Remote", "SSH Target", "PID", "Duration", "Last Error"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[PortMappingRow] = []

    def set_rows(self, rows: list[PortMappingRow]) -> None:
        previous_ids = [row.mapping_id for row in self._rows]
        current_ids = [row.mapping_id for row in rows]
        if previous_ids == current_ids:
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(self.HEADERS) - 1), [])
            return
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
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                self._format_status(row),
                row.name,
                row.local_endpoint,
                row.remote_endpoint,
                row.ssh_target,
                str(row.pid) if row.pid else "-",
                row.duration_text,
                row.last_error,
            ]
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return row.mapping_id
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 0:
            colors = {
                ConnectionStatus.ACTIVE: "#3be38c",
                ConnectionStatus.FAILED: "#ff6b6b",
                ConnectionStatus.CONNECTING: "#5cc8ff",
                ConnectionStatus.RECONNECTING: "#7aa2ff",
            }
            return QColor(colors.get(row.status, "#9ab2c7"))
        return None

    def status_for(self, mapping_id: str) -> ConnectionStatus | None:
        for row in self._rows:
            if row.mapping_id == mapping_id:
                return row.status
        return None

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def mapping_id_at(self, row_index: int) -> str | None:
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index].mapping_id
        return None

    def _format_status(self, row: PortMappingRow) -> str:
        label = row.status.value.upper()
        if row.status in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING}:
            return f"{label}{'.' * (1 + (int(time.time()) % 3))}"
        return label
