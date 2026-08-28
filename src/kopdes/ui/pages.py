from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from kopdes.application.dtos.connection_profile_dto import DashboardStats
from kopdes.application.dtos.runtime_state import (
    ConnectionInspector,
    ConnectionRow,
    HealthCheckResult,
    NetworkSnapshot,
    PortMappingRow,
)
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.shared.enums import ConnectionStatus, HealthCheckType
from kopdes.ui.models.connection_table_model import ConnectionTableModel
from kopdes.ui.models.port_mapping_table_model import PortMappingTableModel
from kopdes.ui.models.profile_table_model import ProfileTableModel
from kopdes.ui.widgets.components import ActionButton, DetailPanel, EmptyState, MetricCard, StatusBadge
from kopdes.ui.widgets.connection_inspector import ConnectionInspectorWidget
from kopdes.ui.widgets.traffic_chart import TrafficChartWidget
from kopdes.ui.widgets.traffic_chart_delegate import TrafficChartDelegate
def _table(table: QTableView | QTableWidget, stretch_column: int = -1) -> None:
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    if isinstance(table, QTableView):
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(stretch_column < 0)
        if stretch_column >= 0:
            table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    else:
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.horizontalHeader().setStretchLastSection(stretch_column < 0)
        if stretch_column >= 0:
            table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)


class ConnectionFilterProxyModel(QSortFilterProxyModel):
    """Apply the state filter and free-text search as an AND expression."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._query = ""
        self._status = "all"

    def set_query(self, query: str) -> None:
        self._query = str(query or "").strip().lower()
        self.invalidateFilter()

    def set_status(self, status: str) -> None:
        self._status = str(status or "all").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        del source_parent
        source = self.sourceModel()
        if source is None:
            return False
        status = str(source.data(source.index(source_row, 0), Qt.ItemDataRole.DisplayRole) or "").lower()
        status_match = {
            "connected": status.startswith("connected"),
            "connecting": status.startswith("connecting"),
            "reconnecting": status.startswith("reconnecting"),
            "failed": status.startswith("failed"),
            "disconnected": status.startswith("disconnected"),
        }
        if self._status != "all" and not status_match.get(self._status, False):
            return False
        if not self._query:
            return True
        return any(
            self._query in str(
                source.data(source.index(source_row, column), Qt.ItemDataRole.DisplayRole) or ""
            ).lower()
            for column in range(source.columnCount())
        )


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        caption = QLabel(subtitle)
        caption.setObjectName("pageSubtitle")
        caption.setWordWrap(True)
        text.addWidget(heading)
        text.addWidget(caption)
        layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)


class OverviewPage(QWidget):
    connections_requested = Signal()
    ssh_requested = Signal()
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cards = {
            "total": MetricCard("Total connections", "0", "#55d7ed"),
            "active": MetricCard("Connected", "0", "#73e6b2"),
            "failed": MetricCard("Failed", "0", "#ff807a"),
            "ssh": MetricCard("SSH tunnels", "0", "#55d7ed"),
            "throughput": MetricCard("Throughput", "0 B/s", "#ffb875"),
            "load": MetricCard("System load", "0.00", "#ffb875"),
        }
        self._activity = QPlainTextEdit()
        self._activity.setReadOnly(True)
        self._activity.setPlaceholderText("No activity recorded yet.")
        self._health = QTableWidget(0, 5)
        self._health.setHorizontalHeaderLabels(["State", "Connection", "Tunnel", "Latency", "Throughput"])
        _table(self._health, 1)
        self._chart = TrafficChartWidget("Aggregate throughput")
        self._updated = QLabel("Waiting for telemetry...")
        self._updated.setObjectName("mutedLabel")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        header = PageHeader("KOPDES Overview", "System operational dashboard. Live data is collected without blocking the interface.")
        refresh = ActionButton("Refresh", "secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.actions.addWidget(refresh)
        root.addWidget(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, card in enumerate(self._cards.values()):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        root.addLayout(cards)

        split = QSplitter(Qt.Orientation.Horizontal)
        activity = DetailPanel("Recent activity", "Operational events from KOPDES and managed network services.")
        activity.body.addWidget(self._activity)
        split.addWidget(activity)
        health = DetailPanel("Network health", "A compact view of live connection state and aggregate traffic.")
        health.body.addWidget(self._chart)
        health.body.addWidget(self._health, 1)
        split.addWidget(health)
        split.setSizes([470, 700])
        root.addWidget(split, 1)
        root.addWidget(self._updated)

    def set_snapshot(
        self,
        stats: DashboardStats,
        rows: list[ConnectionRow],
        logs: list[str],
        port_mapping_rows: list[PortMappingRow] | None = None,
    ) -> None:
        self._cards["total"].set_value(str(stats.total_connections))
        self._cards["active"].set_value(str(stats.active_connections))
        self._cards["failed"].set_value(str(stats.failed_connections))
        self._cards["ssh"].set_value(str(len(port_mapping_rows or [])))
        total_rate = sum(row.rx_rate_bps + row.tx_rate_bps for row in rows)
        self._cards["throughput"].set_value(self._format_rate(total_rate))
        self._cards["load"].set_value(f"{stats.system_load:.2f}")
        self._activity.setPlainText("\n".join(logs[-10:]))
        aggregate_up = self._aggregate_history(rows, "upload_history")
        aggregate_down = self._aggregate_history(rows, "download_history")
        self._chart.set_series(aggregate_up, aggregate_down)
        self._health.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self._health.setItem(index, 0, QTableWidgetItem(self._status_label(row.status)))
            self._health.setItem(index, 1, QTableWidgetItem(row.name))
            self._health.setItem(index, 2, QTableWidgetItem(row.interface_name))
            self._health.setItem(
                index,
                3,
                QTableWidgetItem(f"{row.latency_ms:.1f} ms" if row.latency_ms is not None else "-")
            )
            self._health.setItem(index, 4, QTableWidgetItem(self._format_rate(row.rx_rate_bps + row.tx_rate_bps)))
        self._updated.setText("Telemetry updated")

    def _aggregate_history(self, rows: list[ConnectionRow], attribute: str) -> list[float]:
        histories = [getattr(row, attribute) for row in rows if getattr(row, attribute)]
        if not histories:
            return []
        width = max(len(history) for history in histories)
        return [
            sum(history[index] for history in histories if index < len(history))
            for index in range(width)
        ]

    def _status_label(self, status: ConnectionStatus) -> str:
        return {
            ConnectionStatus.ACTIVE: "CONNECTED",
            ConnectionStatus.INACTIVE: "DISCONNECTED",
            ConnectionStatus.CONNECTING: "CONNECTING",
            ConnectionStatus.RECONNECTING: "RECONNECTING",
            ConnectionStatus.DISCONNECTING: "DISCONNECTING",
            ConnectionStatus.FAILED: "FAILED",
            ConnectionStatus.DEGRADED: "DEGRADED",
        }.get(status, "UNKNOWN")

    def _format_rate(self, value: float) -> str:
        units = ("B/s", "KB/s", "MB/s", "GB/s")
        size = float(max(value, 0.0))
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB/s"


class ConnectionsPage(QWidget):
    profile_selected = Signal(str)
    connect_requested = Signal(str)
    disconnect_requested = Signal(str)
    reconnect_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    add_requested = Signal()
    import_requested = Signal()
    refresh_requested = Signal()
    route_add_requested = Signal()
    route_delete_requested = Signal(str, str)
    route_metric_change_requested = Signal(str, str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.model = ConnectionTableModel()
        self.proxy = ConnectionFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        _table(self.table, 1)
        self.table.setItemDelegateForColumn(7, TrafficChartDelegate(self.table))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search name, server, interface, backend, or error")
        self._status_filter = QComboBox()
        self._status_filter.addItem("All states", "all")
        for status in ("connected", "connecting", "reconnecting", "failed", "disconnected"):
            self._status_filter.addItem(status.upper(), status)
        self._inspector = ConnectionInspectorWidget()
        self._details_stack = QWidget()
        self._selected_id: str | None = None
        self._busy_ids: set[str] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = PageHeader("Connections", "Manage OpenVPN, PPP, PPTP, L2TP, and PPPoE sessions from one workspace.")
        add = ActionButton("Add connection", "primary")
        add.clicked.connect(self.add_requested.emit)
        import_button = ActionButton("Import OVPN", "secondary")
        import_button.clicked.connect(self.import_requested.emit)
        refresh = ActionButton("Refresh", "secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.actions.addWidget(import_button)
        header.actions.addWidget(add)
        header.actions.addWidget(refresh)
        root.addWidget(header)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self._filter, 1)
        filters.addWidget(self._status_filter)
        root.addLayout(filters)

        split = QSplitter(Qt.Orientation.Horizontal)
        list_panel = DetailPanel("Connection fleet", "Select a row to inspect tunnel, route, DNS, and traffic telemetry.")
        actions = QHBoxLayout()
        for label, signal, variant in (
            ("Connect", self.connect_requested, "primary"),
            ("Disconnect", self.disconnect_requested, "secondary"),
            ("Reconnect", self.reconnect_requested, "secondary"),
            ("Edit", self.edit_requested, "secondary"),
            ("Delete", self.delete_requested, "danger"),
        ):
            button = ActionButton(label, variant)
            button.clicked.connect(lambda _checked=False, emitted=signal: self._emit_selected(emitted))
            actions.addWidget(button)
            setattr(self, f"_{label.lower()}_button", button)
        actions.addStretch(1)
        list_panel.body.addLayout(actions)
        list_panel.body.addWidget(self.table, 1)
        split.addWidget(list_panel)

        inspector_panel = DetailPanel("Connection inspector", "Tunnel state, routes, DNS, interface counters, and speed fluctuation.")
        inspector_panel.body.addWidget(self._inspector, 1)
        split.addWidget(inspector_panel)
        split.setSizes([720, 560])
        root.addWidget(split, 1)

        self._filter.textChanged.connect(self.proxy.set_query)
        self._status_filter.currentIndexChanged.connect(self._apply_status_filter)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self._inspector.route_add_requested.connect(self.route_add_requested.emit)
        self._inspector.route_delete_requested.connect(self.route_delete_requested.emit)
        self._inspector.route_metric_change_requested.connect(self.route_metric_change_requested.emit)
        self.table.doubleClicked.connect(lambda _index: self._emit_selected(self.edit_requested))

    def set_rows(self, rows: list[ConnectionRow]) -> None:
        selected = self._selected_id
        self.model.set_rows(rows)
        self._restore_selection(selected)
        self._update_action_buttons()

    def set_inspector(self, inspector: ConnectionInspector | None) -> None:
        self._inspector.set_inspector(inspector)

    def set_action_state(self, profile_id: str, operation: str | None) -> None:
        if operation is None:
            self._busy_ids.discard(profile_id)
            self.model.clear_status_override(profile_id)
        else:
            self._busy_ids.add(profile_id)
            if operation in {"connect", "reconnect"}:
                self.model.set_status_override(
                    profile_id,
                    ConnectionStatus.CONNECTING
                    if operation == "connect"
                    else ConnectionStatus.RECONNECTING,
                )
            elif operation == "disconnect":
                self.model.set_status_override(profile_id, ConnectionStatus.DISCONNECTING)
        self._update_action_buttons()

    def selected_profile_id(self) -> str | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        source = self.proxy.mapToSource(indexes[0])
        return self.model.profile_id_at(source.row())

    def set_global_filter(self, text: str) -> None:
        self._filter.setText(text)

    def _emit_selected(self, signal) -> None:
        profile_id = self.selected_profile_id()
        if profile_id:
            signal.emit(profile_id)

    def _selection_changed(self) -> None:
        profile_id = self.selected_profile_id()
        self._selected_id = profile_id
        self._update_action_buttons()
        self.profile_selected.emit(profile_id or "")

    def _restore_selection(self, profile_id: str | None) -> None:
        if not profile_id:
            return
        for row in range(self.model.rowCount()):
            if self.model.profile_id_at(row) != profile_id:
                continue
            source = self.model.index(row, 0)
            proxy = self.proxy.mapFromSource(source)
            if proxy.isValid():
                self.table.selectRow(proxy.row())
            return

    def _update_action_buttons(self) -> None:
        selected = self.selected_profile_id()
        if not selected:
            for name in ("_connect_button", "_disconnect_button", "_reconnect_button", "_edit_button", "_delete_button"):
                getattr(self, name).setEnabled(False)
            return
        status = self.model.status_for(selected) or ConnectionStatus.INACTIVE
        busy = selected in self._busy_ids
        transitioning = status in {
            ConnectionStatus.CONNECTING,
            ConnectionStatus.RECONNECTING,
            ConnectionStatus.DISCONNECTING,
        }
        self._connect_button.setEnabled(not busy and status in {ConnectionStatus.INACTIVE, ConnectionStatus.FAILED})
        self._disconnect_button.setEnabled(not busy and status in {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.DEGRADED,
            ConnectionStatus.CONNECTING,
            ConnectionStatus.RECONNECTING,
        })
        self._reconnect_button.setEnabled(not busy and not transitioning)
        self._edit_button.setEnabled(not busy)
        self._delete_button.setEnabled(not busy)

    def _apply_status_filter(self) -> None:
        self.proxy.set_status(str(self._status_filter.currentData() or "all"))


class SshTunnelsPage(QWidget):
    mapping_selected = Signal(str)
    add_requested = Signal()
    edit_requested = Signal(str)
    connect_requested = Signal(str)
    disconnect_requested = Signal(str)
    delete_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.model = PortMappingTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        _table(self.table, 1)
        self._rows: list[PortMappingRow] = []
        self._selected_id: str | None = None
        self._busy_ids: set[str] = set()
        self._detail_labels: dict[str, QLabel] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = PageHeader("SSH Tunnels", "Manage local and remote port forwarding with explicit process ownership.")
        for label, signal, variant in (("Refresh", self.refresh_requested, "secondary"), ("Add mapping", self.add_requested, "primary")):
            button = ActionButton(label, variant)
            button.clicked.connect(signal.emit)
            header.actions.addWidget(button)
        root.addWidget(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        list_panel = DetailPanel("Active mappings", "Each row maps a local listening port through one managed SSH process.")
        actions = QHBoxLayout()
        for label, signal, variant in (
            ("Connect", self.connect_requested, "primary"),
            ("Disconnect", self.disconnect_requested, "secondary"),
            ("Edit", self.edit_requested, "secondary"),
            ("Delete", self.delete_requested, "danger"),
        ):
            button = ActionButton(label, variant)
            button.clicked.connect(lambda _checked=False, emitted=signal: self._emit_selected(emitted))
            actions.addWidget(button)
            setattr(self, f"_{label.lower()}_button", button)
        actions.addStretch(1)
        list_panel.body.addLayout(actions)
        list_panel.body.addWidget(self.table, 1)
        split.addWidget(list_panel)

        details = DetailPanel("Tunnel path", "Local endpoint to remote service through the SSH target.")
        diagram = QFrame()
        diagram.setObjectName("mappingDiagram")
        diagram_layout = QVBoxLayout(diagram)
        diagram_layout.setContentsMargins(18, 18, 18, 18)
        for key in ("status", "local", "target", "remote", "pid", "duration", "error"):
            label = QLabel("-")
            label.setObjectName("mappingDetailValue")
            self._detail_labels[key] = label
            diagram_layout.addWidget(label)
        diagram_layout.addStretch(1)
        details.body.addWidget(diagram, 1)
        split.addWidget(details)
        split.setSizes([760, 420])
        root.addWidget(split, 1)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)

    def set_rows(self, rows: list[PortMappingRow]) -> None:
        self._rows = rows
        selected = self._selected_id
        self.model.set_rows(rows)
        if selected:
            for index, row in enumerate(rows):
                if row.mapping_id == selected:
                    proxy_index = self.proxy.mapFromSource(self.model.index(index, 0))
                    if proxy_index.isValid():
                        self.table.selectRow(proxy_index.row())
                    break
        self._update_details()
        self._update_action_buttons()

    def selected_mapping_id(self) -> str | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        source = self.proxy.mapToSource(index)
        return self.model.mapping_id_at(source.row())

    def set_action_state(self, busy: bool, mapping_id: str | None = None) -> None:
        if mapping_id is None:
            if busy:
                self._busy_ids.add("*")
            else:
                self._busy_ids.clear()
        elif busy:
            self._busy_ids.add(mapping_id)
        else:
            self._busy_ids.discard(mapping_id)
        self._update_action_buttons()

    def set_global_filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)

    def _emit_selected(self, signal) -> None:
        mapping_id = self.selected_mapping_id()
        if mapping_id:
            signal.emit(mapping_id)

    def _selection_changed(self) -> None:
        self._selected_id = self.selected_mapping_id()
        self._update_details()
        self._update_action_buttons()
        self.mapping_selected.emit(self._selected_id or "")

    def _update_action_buttons(self) -> None:
        selected = self.selected_mapping_id()
        if not selected:
            for name in ("_connect_button", "_disconnect_button", "_edit_button", "_delete_button"):
                getattr(self, name).setEnabled(False)
            return
        status = self.model.status_for(selected) or ConnectionStatus.INACTIVE
        busy = "*" in self._busy_ids or selected in self._busy_ids
        transitioning = status in {ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING}
        self._connect_button.setEnabled(not busy and status in {ConnectionStatus.INACTIVE, ConnectionStatus.FAILED})
        self._disconnect_button.setEnabled(not busy and status in {ConnectionStatus.ACTIVE, ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING})
        self._edit_button.setEnabled(not busy)
        self._delete_button.setEnabled(not busy and not transitioning)

    def _update_details(self) -> None:
        mapping = next((row for row in self._rows if row.mapping_id == self._selected_id), None)
        values = {
            "status": self._status_line(mapping.status) if mapping else "No tunnel selected",
            "local": f"LOCAL  {mapping.local_endpoint}" if mapping else "LOCAL  -",
            "target": f"SSH     {mapping.ssh_target}" if mapping else "SSH     -",
            "remote": f"REMOTE  {mapping.remote_endpoint}" if mapping else "REMOTE  -",
            "pid": f"PID     {mapping.pid or '-'}" if mapping else "PID     -",
            "duration": f"UPTIME  {mapping.duration_text}" if mapping else "UPTIME  -",
            "error": f"ERROR   {mapping.last_error}" if mapping and mapping.last_error != "-" else "",
        }
        for key, label in self._detail_labels.items():
            label.setText(values[key])
            label.setVisible(bool(values[key]))

    def _status_line(self, status: ConnectionStatus) -> str:
        return f"STATUS  {status.value.upper()}"


class ProfilesPage(QWidget):
    profile_selected = Signal(str)
    add_requested = Signal()
    import_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.model = ProfileTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        _table(self.table, 2)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search profiles, protocol, server, or tags")
        self._selected_id: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = PageHeader("VPN Profiles", "Edit encrypted credentials and protocol configuration without touching runtime state.")
        for label, signal, variant in (
            ("Import OVPN", self.import_requested, "secondary"),
            ("Add profile", self.add_requested, "primary"),
            ("Refresh", self.refresh_requested, "secondary"),
        ):
            button = ActionButton(label, variant)
            button.clicked.connect(signal.emit)
            header.actions.addWidget(button)
        root.addWidget(header)
        root.addWidget(self._filter)
        panel = DetailPanel("Stored connection profiles", "Passwords are represented only by an encrypted-storage indicator.")
        actions = QHBoxLayout()
        for label, signal, variant in (("Edit", self.edit_requested, "secondary"), ("Delete", self.delete_requested, "danger")):
            button = ActionButton(label, variant)
            button.clicked.connect(lambda _checked=False, emitted=signal: self._emit_selected(emitted))
            actions.addWidget(button)
        actions.addStretch(1)
        panel.body.addLayout(actions)
        panel.body.addWidget(self.table, 1)
        root.addWidget(panel, 1)
        self._filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._emit_selected(self.edit_requested))

    def set_profiles(self, profiles: list[ConnectionProfile], statuses: dict[str, ConnectionStatus]) -> None:
        self.model.set_profiles(profiles, statuses)
        if self._selected_id:
            for row in range(self.model.rowCount()):
                if self.model.profile_id_at(row) == self._selected_id:
                    proxy = self.proxy.mapFromSource(self.model.index(row, 0))
                    if proxy.isValid():
                        self.table.selectRow(proxy.row())
                    break

    def set_global_filter(self, text: str) -> None:
        self._filter.setText(text)

    def selected_profile_id(self) -> str | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model.profile_id_at(self.proxy.mapToSource(indexes[0]).row())

    def _emit_selected(self, signal) -> None:
        profile_id = self.selected_profile_id()
        if profile_id:
            signal.emit(profile_id)

    def _selection_changed(self) -> None:
        self._selected_id = self.selected_profile_id()
        self.profile_selected.emit(self._selected_id or "")


class NetworkPage(QWidget):
    refresh_requested = Signal()
    route_add_requested = Signal()
    route_delete_requested = Signal(str, str)
    route_metric_change_requested = Signal(str, str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self._interfaces = QTableWidget(0, 9)
        self._interfaces.setHorizontalHeaderLabels(["Interface", "Type", "State", "IPv4", "RX", "TX", "RX rate", "TX rate", "MTU"])
        self._routes = QTableWidget(0, 6)
        self._routes.setHorizontalHeaderLabels(["Destination", "Gateway", "Device", "Table", "Metric", "Protocol"])
        self._rules = QTableWidget(0, 5)
        self._rules.setHorizontalHeaderLabels(["Priority", "Source", "Destination", "Table", "Action"])
        _table(self._interfaces, 0)
        _table(self._routes, 0)
        _table(self._rules, 1)
        self._dns = QPlainTextEdit()
        self._dns.setReadOnly(True)
        self._last_snapshot: NetworkSnapshot | None = None
        self._empty = EmptyState("Waiting for interface and routing telemetry...")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = PageHeader("Interfaces & Routing", "Inspect tun, tap, ppp interfaces, Linux routes, policy rules, and resolver state.")
        refresh = ActionButton("Refresh", "secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.actions.addWidget(refresh)
        root.addWidget(header)
        tabs = QTabWidget()
        tabs.addTab(self._interface_tab(), "Interfaces")
        tabs.addTab(self._route_tab(), "Routes")
        tabs.addTab(self._rules, "Policy rules")
        tabs.addTab(self._dns, "DNS")
        root.addWidget(tabs, 1)

    def _interface_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._interfaces, 1)
        return widget

    def _route_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        add = ActionButton("Add route", "primary")
        add.clicked.connect(self.route_add_requested.emit)
        delete = ActionButton("Delete route", "danger")
        delete.clicked.connect(self._emit_delete_route)
        metric = ActionButton("Change metric", "secondary")
        metric.clicked.connect(self._emit_metric_change)
        actions.addWidget(add)
        actions.addWidget(delete)
        actions.addWidget(metric)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self._routes, 1)
        return widget

    def set_snapshot(self, snapshot: NetworkSnapshot) -> None:
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot
        self._interfaces.setRowCount(len(snapshot.interfaces))
        for row_index, item in enumerate(snapshot.interfaces):
            values = [
                item.name,
                item.kind.upper(),
                "UP" if item.is_up else "DOWN",
                item.ipv4 or "-",
                self._format_bytes(item.rx_bytes),
                self._format_bytes(item.tx_bytes),
                self._format_rate(item.rx_rate_bps),
                self._format_rate(item.tx_rate_bps),
                str(item.mtu),
            ]
            self._set_row(self._interfaces, row_index, values)

        self._routes.setRowCount(len(snapshot.routes))
        for row_index, item in enumerate(snapshot.routes):
            self._set_row(
                self._routes,
                row_index,
                [item.destination, item.gateway or "-", item.device or "-", item.table, str(item.metric or "-"), item.protocol or "-"],
            )

        self._rules.setRowCount(len(snapshot.rules))
        for row_index, item in enumerate(snapshot.rules):
            self._set_row(
                self._rules,
                row_index,
                [str(item.priority or "-"), item.source or "-", item.destination or "-", item.table or "-", item.action or "-"],
            )
        self._dns.setPlainText(
            "\n".join(
                (
                    f"Resolver: {snapshot.dns.resolver_source}",
                    f"Nameservers: {', '.join(snapshot.dns.servers) or '-'}",
                    f"Search domains: {', '.join(snapshot.dns.search_domains) or '-'}",
                )
            )
        )

    def _emit_delete_route(self) -> None:
        row = self._routes.currentRow()
        if row < 0:
            return
        self.route_delete_requested.emit(self._routes.item(row, 0).text(), self._routes.item(row, 3).text())

    def _emit_metric_change(self) -> None:
        row = self._routes.currentRow()
        if row < 0:
            return
        self.route_metric_change_requested.emit(
            self._routes.item(row, 0).text(),
            self._routes.item(row, 1).text(),
            self._routes.item(row, 2).text(),
            self._routes.item(row, 3).text(),
        )

    def _set_row(self, table: QTableWidget, row: int, values: Iterable[str]) -> None:
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))

    def _format_bytes(self, value: int) -> str:
        units = ("B", "KB", "MB", "GB", "TB")
        size = float(max(value, 0))
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _format_rate(self, value: float) -> str:
        return f"{self._format_bytes(int(value))}/s"


class LogsPage(QWidget):
    refresh_requested = Signal()
    export_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._logs: list[str] = []
        self._last_visible: tuple[str, ...] = ()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search event type, connection, severity, or message")
        self._level = QComboBox()
        self._level.addItems(["ALL LEVELS", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"])
        self._viewer = QPlainTextEdit()
        self._viewer.setReadOnly(True)
        self._count = QLabel("0 events")
        self._count.setObjectName("mutedLabel")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header = PageHeader("Logs & Diagnostics", "Review structured activity without loading unbounded log history into memory.")
        refresh = ActionButton("Refresh", "secondary")
        refresh.clicked.connect(self.refresh_requested.emit)
        export = ActionButton("Export", "secondary")
        export.clicked.connect(self._export)
        header.actions.addWidget(refresh)
        header.actions.addWidget(export)
        root.addWidget(header)
        filters = QHBoxLayout()
        filters.addWidget(self._filter, 1)
        filters.addWidget(self._level)
        root.addLayout(filters)
        panel = DetailPanel("System stream", "KOPDES events, connection lifecycle, route actions, and SSH tunnel events.")
        panel.body.addWidget(self._viewer, 1)
        panel.body.addWidget(self._count)
        root.addWidget(panel, 1)
        self._filter.textChanged.connect(self._apply_filter)
        self._level.currentTextChanged.connect(self._apply_filter)

    def set_logs(self, logs: list[str]) -> None:
        incoming = list(logs)
        if incoming == self._logs:
            return
        self._logs = incoming
        self._apply_filter()

    def set_global_filter(self, text: str) -> None:
        self._filter.setText(text)

    def _apply_filter(self) -> None:
        query = self._filter.text().strip().lower()
        level = self._level.currentText().lower()
        visible = [
            line
            for line in self._logs
            if (not query or query in line.lower())
            and (level == "all levels" or f" {level} " in line.lower())
        ]
        visible_entries = tuple(visible)
        if visible_entries != self._last_visible:
            self._last_visible = visible_entries
            self._viewer.setPlainText("\n".join(visible))
        self._count.setText(f"{len(visible)} events")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export KOPDES Logs", str(Path.home() / "kopdes.log"), "Log files (*.log *.txt)")
        if not path:
            return
        self.export_requested.emit(path, self._viewer.toPlainText())


class DiagnosticsPage(QWidget):
    run_requested = Signal(str, str, int)

    def __init__(self) -> None:
        super().__init__()
        self._check_type = QComboBox()
        self._check_type.addItem("Ping", HealthCheckType.PING.value)
        self._check_type.addItem("TCP port", HealthCheckType.TCP.value)
        self._target = QLineEdit()
        self._target.setPlaceholderText("8.8.8.8 or host:port")
        self._timeout = QSpinBox()
        self._timeout.setRange(1, 30)
        self._timeout.setValue(3)
        self._status = StatusBadge("unknown")
        self._run_button: QPushButton | None = None
        self._result = QPlainTextEdit()
        self._result.setReadOnly(True)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(PageHeader("Diagnostics", "Run bounded network checks in a worker and keep command output separated from the UI thread."))
        panel = DetailPanel("Health check", "Ping and TCP checks are executed through the application health service.")
        form = QFormLayout()
        form.addRow("Check", self._check_type)
        form.addRow("Target", self._target)
        form.addRow("Timeout (s)", self._timeout)
        run = ActionButton("Run check", "primary")
        run.clicked.connect(self._emit_run)
        self._run_button = run
        form.addRow("", run)
        panel.body.addLayout(form)
        summary = QHBoxLayout()
        summary.addWidget(QLabel("Result"))
        summary.addWidget(self._status)
        summary.addStretch(1)
        panel.body.addLayout(summary)
        panel.body.addWidget(self._result, 1)
        root.addWidget(panel, 1)

    def set_running(self) -> None:
        self._status.set_status(ConnectionStatus.CONNECTING)
        self._result.setPlainText("Running diagnostic...")
        if self._run_button is not None:
            self._run_button.setEnabled(False)

    def set_result(self, result: HealthCheckResult) -> None:
        self._status.set_status("active" if result.ok else "failed")
        if self._run_button is not None:
            self._run_button.setEnabled(True)
        latency = f"Latency: {result.latency_ms:.2f} ms\n" if result.latency_ms is not None else ""
        self._result.setPlainText(f"{latency}{result.detail or 'No additional detail.'}")

    def set_error(self, error: Exception) -> None:
        self._status.set_status("failed")
        self._result.setPlainText(str(error).strip() or error.__class__.__name__)
        if self._run_button is not None:
            self._run_button.setEnabled(True)

    def _emit_run(self) -> None:
        target = self._target.text().strip()
        if target:
            self.run_requested.emit(str(self._check_type.currentData()), target, self._timeout.value())


class SettingsPage(QWidget):
    def __init__(self, data_dir: Path | None, database_url: str | None, refresh_interval_ms: int) -> None:
        super().__init__()
        self._data_dir = data_dir
        self._database_url = database_url
        self._refresh_interval_ms = refresh_interval_ms
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(PageHeader("Settings", "Runtime paths and safety policies for this desktop node."))
        panel = DetailPanel("Runtime configuration", "These values are read from the active KOPDES configuration.")
        form = QFormLayout()
        form.addRow("Data directory", QLabel(str(self._data_dir or "-")))
        form.addRow("Database", QLabel(str(self._database_url or "-")))
        form.addRow("Telemetry interval", QLabel(f"{self._refresh_interval_ms} ms"))
        form.addRow("Credential storage", QLabel("Encrypted local secret key"))
        form.addRow("Process ownership", QLabel("Only KOPDES-managed runtime metadata is eligible for cleanup"))
        panel.body.addLayout(form)
        policy = QLabel(
            "Network operations require explicit operator actions. Background monitoring is bounded and does not restart failed sessions indefinitely."
        )
        policy.setObjectName("calloutLabel")
        policy.setWordWrap(True)
        panel.body.addWidget(policy)
        panel.body.addStretch(1)
        root.addWidget(panel, 1)
