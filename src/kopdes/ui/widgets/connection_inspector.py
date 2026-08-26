from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from kopdes.application.dtos.runtime_state import ConnectionInspector
from kopdes.ui.widgets.traffic_chart import TrafficChartWidget


class ConnectionInspectorWidget(QWidget):
    route_add_requested = Signal()
    route_delete_requested = Signal(str, str)
    route_metric_change_requested = Signal(str, str, str, str)

    def __init__(self) -> None:
        super().__init__()
        self._labels: dict[str, QLabel] = {}
        self._route_table = QTableWidget(0, 5)
        self._route_table.setHorizontalHeaderLabels(["Destination", "Gateway", "Device", "Table", "Metric"])
        self._interface_table = QTableWidget(0, 7)
        self._interface_table.setHorizontalHeaderLabels(["Name", "Type", "IP", "RX", "TX", "Errors", "MTU"])
        self._dns_view = QTextEdit()
        self._dns_view.setReadOnly(True)
        self._logs_view = QTextEdit()
        self._logs_view.setReadOnly(True)
        self._traffic_chart = TrafficChartWidget("Upload / Download Fluctuation")
        self._headline = QLabel("Connection Inspector")
        self._headline.setStyleSheet("font-size: 22px; font-weight: 700; color: #eff7ff;")
        self._subheadline = QLabel("Pilih koneksi untuk melihat health, tunnel, route, DNS, dan bottleneck traffic.")
        self._subheadline.setStyleSheet("color: #7fa1bb;")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._headline)
        layout.addWidget(self._subheadline)

        top = QHBoxLayout()
        metrics_card = QWidget()
        metrics_card.setObjectName("metricsCard")
        metrics_layout = QGridLayout(metrics_card)
        keys = [
            "Backend",
            "Status",
            "Tunnel IP",
            "Gateway",
            "DNS",
            "Upload",
            "Download",
            "Latency",
            "Packet Loss",
            "MTU",
            "Reconnect Count",
            "Last Error",
        ]
        for idx, key in enumerate(keys):
            title = QLabel(key)
            title.setStyleSheet("color: #7fa1bb; font-size: 11px; text-transform: uppercase;")
            value = QLabel("-")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet("font-size: 14px; font-weight: 600; color: #edf6ff;")
            self._labels[key] = value
            row = idx // 2
            col = (idx % 2) * 2
            metrics_layout.addWidget(title, row, col)
            metrics_layout.addWidget(value, row, col + 1)
        top.addWidget(metrics_card, 4)
        top.addWidget(self._traffic_chart, 5)
        layout.addLayout(top, stretch=3)

        tabs = QTabWidget()
        tabs.addTab(self._route_tab(), "Routes")
        tabs.addTab(self._interface_table, "Interfaces")
        tabs.addTab(self._dns_view, "DNS")
        tabs.addTab(self._logs_view, "Logs")
        layout.addWidget(tabs, stretch=4)

    def _route_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        row = QHBoxLayout()
        add_button = QPushButton("Add Route")
        delete_button = QPushButton("Delete Route")
        metric_button = QPushButton("Change Metric")
        add_button.clicked.connect(self.route_add_requested.emit)
        delete_button.clicked.connect(self._emit_delete_route)
        metric_button.clicked.connect(self._emit_metric_change)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        row.addWidget(metric_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self._route_table, stretch=1)
        return widget

    def set_inspector(self, inspector: ConnectionInspector | None) -> None:
        if inspector is None:
            self._headline.setText("Connection Inspector")
            self._subheadline.setText("Pilih koneksi untuk melihat health, tunnel, route, DNS, dan bottleneck traffic.")
            for label in self._labels.values():
                label.setText("-")
            self._route_table.setRowCount(0)
            self._interface_table.setRowCount(0)
            self._dns_view.clear()
            self._logs_view.clear()
            self._traffic_chart.set_series([], [])
            return

        row = inspector.row
        self._headline.setText(inspector.profile.name)
        self._subheadline.setText(f"{inspector.profile.protocol.value} | {inspector.profile.server_address}")
        values = {
            "Backend": row.backend,
            "Status": row.status.value,
            "Tunnel IP": inspector.tunnel_ip,
            "Gateway": inspector.gateway,
            "DNS": inspector.dns_display,
            "Upload": self._format_rate(row.tx_rate_bps, row.total_tx_bytes),
            "Download": self._format_rate(row.rx_rate_bps, row.total_rx_bytes),
            "Latency": f"{row.latency_ms:.2f} ms" if row.latency_ms is not None else "-",
            "Packet Loss": inspector.packet_loss,
            "MTU": inspector.mtu,
            "Reconnect Count": str(inspector.reconnect_count),
            "Last Error": row.last_error,
        }
        for key, value in values.items():
            self._labels[key].setText(value)
        self._traffic_chart.set_series(inspector.upload_history, inspector.download_history)

        self._route_table.setRowCount(len(inspector.routes))
        for index, route in enumerate(inspector.routes):
            self._route_table.setItem(index, 0, QTableWidgetItem(route.destination))
            self._route_table.setItem(index, 1, QTableWidgetItem(route.gateway or "-"))
            self._route_table.setItem(index, 2, QTableWidgetItem(route.device or "-"))
            self._route_table.setItem(index, 3, QTableWidgetItem(route.table))
            self._route_table.setItem(index, 4, QTableWidgetItem(str(route.metric) if route.metric is not None else "-"))

        self._interface_table.setRowCount(len(inspector.interfaces))
        for index, interface in enumerate(inspector.interfaces):
            self._interface_table.setItem(index, 0, QTableWidgetItem(interface.name))
            self._interface_table.setItem(index, 1, QTableWidgetItem(interface.kind))
            self._interface_table.setItem(index, 2, QTableWidgetItem(interface.ipv4 or "-"))
            self._interface_table.setItem(index, 3, QTableWidgetItem(self._format_bytes(interface.rx_bytes)))
            self._interface_table.setItem(index, 4, QTableWidgetItem(self._format_bytes(interface.tx_bytes)))
            self._interface_table.setItem(index, 5, QTableWidgetItem(f"{interface.err_in}/{interface.err_out}"))
            self._interface_table.setItem(index, 6, QTableWidgetItem(str(interface.mtu)))

        dns_text = "\n".join(
            [
                f"Resolver: {inspector.dns.resolver_source}",
                f"Servers: {', '.join(inspector.dns.servers) if inspector.dns.servers else '-'}",
                f"Search: {', '.join(inspector.dns.search_domains) if inspector.dns.search_domains else '-'}",
            ]
        )
        self._dns_view.setPlainText(dns_text)
        self._logs_view.setPlainText("\n".join(inspector.log_messages))

    def _emit_delete_route(self) -> None:
        row = self._route_table.currentRow()
        if row < 0:
            return
        destination = self._route_table.item(row, 0).text()
        table = self._route_table.item(row, 3).text()
        self.route_delete_requested.emit(destination, table)

    def _emit_metric_change(self) -> None:
        row = self._route_table.currentRow()
        if row < 0:
            return
        destination = self._route_table.item(row, 0).text()
        gateway = self._route_table.item(row, 1).text()
        device = self._route_table.item(row, 2).text()
        table = self._route_table.item(row, 3).text()
        self.route_metric_change_requested.emit(destination, gateway, device, table)

    def _format_rate(self, rate_bps: float, total_bytes: int) -> str:
        return f"{self._format_bytes(int(rate_bps))}/s ({self._format_bytes(total_bytes)})"

    def _format_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
