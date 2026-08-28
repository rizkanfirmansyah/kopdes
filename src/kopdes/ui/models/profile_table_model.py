from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.shared.enums import ConnectionStatus


class ProfileTableModel(QAbstractTableModel):
    HEADERS = ["Name", "Protocol", "Server", "Authentication", "Tags", "State"]

    def __init__(self) -> None:
        super().__init__()
        self._profiles: list[ConnectionProfile] = []
        self._statuses: dict[str, ConnectionStatus] = {}

    def set_profiles(
        self,
        profiles: list[ConnectionProfile],
        statuses: dict[str, ConnectionStatus] | None = None,
    ) -> None:
        statuses = statuses or {}
        profile_ids = [profile.id for profile in profiles]
        old_ids = [profile.id for profile in self._profiles]
        if profile_ids != old_ids:
            self.beginResetModel()
            self._profiles = profiles
            self._statuses = statuses
            self.endResetModel()
            return
        self._profiles = profiles
        self._statuses = statuses
        if self._profiles:
            top = self.index(0, 0)
            bottom = self.index(len(self._profiles) - 1, len(self.HEADERS) - 1)
            self.dataChanged.emit(top, bottom, [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(self._profiles)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._profiles):
            return None
        profile = self._profiles[index.row()]
        status = self._statuses.get(profile.id, ConnectionStatus.INACTIVE)
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                profile.name,
                profile.protocol.value.upper(),
                profile.server_address or "-",
                "Stored" if profile.encrypted_password else "Not set",
                ", ".join(profile.tags) if profile.tags else "-",
                self._status_label(status),
            ]
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return profile.id
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 5:
            colors = {
                ConnectionStatus.ACTIVE: "#73e6b2",
                ConnectionStatus.FAILED: "#ff9c97",
                ConnectionStatus.CONNECTING: "#55d7ed",
                ConnectionStatus.RECONNECTING: "#9dbeff",
                ConnectionStatus.DEGRADED: "#ffbd78",
            }
            return QColor(colors.get(status, "#a6b4b8"))
        return None

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def profile_id_at(self, row_index: int) -> str | None:
        if 0 <= row_index < len(self._profiles):
            return self._profiles[row_index].id
        return None

    def _status_label(self, status: ConnectionStatus) -> str:
        return {
            ConnectionStatus.ACTIVE: "CONNECTED",
            ConnectionStatus.INACTIVE: "DISCONNECTED",
            ConnectionStatus.CONNECTING: "CONNECTING",
            ConnectionStatus.DISCONNECTING: "DISCONNECTING",
            ConnectionStatus.RECONNECTING: "RECONNECTING",
            ConnectionStatus.FAILED: "FAILED",
            ConnectionStatus.DEGRADED: "DEGRADED",
        }.get(status, "UNKNOWN")
