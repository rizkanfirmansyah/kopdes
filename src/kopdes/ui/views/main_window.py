from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.ui.dialogs.profile_dialog import ProfileDialog
from kopdes.ui.models.connection_table_model import ConnectionTableModel
from kopdes.ui.widgets.connection_inspector import ConnectionInspectorWidget
from kopdes.ui.widgets.log_viewer import LogViewer
from kopdes.ui.widgets.port_mapping_panel import PortMappingPanel
from kopdes.ui.widgets.status_card import StatusCard
from kopdes.ui.widgets.terminal_panel import TerminalPanel
from kopdes.ui.widgets.traffic_chart_delegate import TrafficChartDelegate


LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        control_center_service: ControlCenterService,
        terminal_panel: TerminalPanel,
        refresh_interval_ms: int,
    ) -> None:
        super().__init__()
        self._control_center_service = control_center_service
        self._terminal_panel = terminal_panel
        self._table_model = ConnectionTableModel()
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._table_model)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy_model.setFilterKeyColumn(-1)
        self._log_viewer = LogViewer()
        self._inspector = ConnectionInspectorWidget()
        self._port_mapping_panel = PortMappingPanel(control_center_service)
        self._selected_profile_id: str | None = None
        self._shutting_down = False
        self._monitoring_error_reported = False
        self._logo_path = Path(__file__).resolve().parents[4] / "logo.png"

        self.setWindowTitle("KOPDES")
        self.resize(1680, 980)
        self._apply_window_icon()
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(max(int(refresh_interval_ms), 250))

        self._status_animation_timer = QTimer(self)
        self._status_animation_timer.timeout.connect(self._table.viewport().update)
        self._status_animation_timer.start(1000)

        self.refresh()

    def _build_ui(self) -> None:
        self.setStatusBar(QStatusBar())
        root = QWidget()
        shell = QVBoxLayout(root)
        shell.setContentsMargins(18, 18, 18, 18)
        shell.setSpacing(14)
        shell.addWidget(self._build_navbar())
        shell.addLayout(self._build_cards())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([980, 620])
        shell.addWidget(splitter, 1)

        self.setCentralWidget(root)
        self._build_bottom_dock()
        self._wire_signals()
        self._apply_style()

    def _build_navbar(self) -> QWidget:
        card = QFrame()
        card.setObjectName("navCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)
        layout.addLayout(self._build_brand_block(), 1)

        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText("Search connections, interface, gateway, backend, or error")
        self._global_search.setMinimumWidth(320)
        layout.addWidget(self._global_search)

        import_button = QPushButton("Import OVPN")
        import_button.clicked.connect(self._import_ovpn)
        mapping_button = QPushButton("SSH Mapping")
        mapping_button.clicked.connect(self._open_port_mapping)
        add_button = QPushButton("+ Add New")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._add_profile)
        layout.addWidget(import_button)
        layout.addWidget(mapping_button)
        layout.addWidget(add_button)
        return card

    def _open_port_mapping(self) -> None:
        self._bottom_dock.show()
        self._bottom_tabs.setCurrentWidget(self._port_mapping_panel)
        self._port_mapping_panel.add_mapping()

    def _build_brand_block(self):
        row = QHBoxLayout()
        row.setSpacing(14)

        logo = QLabel()
        logo.setObjectName("navLogo")
        if self._logo_path.exists():
            pixmap = QPixmap(str(self._logo_path)).scaled(
                36,
                36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pixmap)
        else:
            logo.setText("K")
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        title = QLabel("KOPDES")
        title.setObjectName("brandLabel")
        subtitle = QLabel("Konfigurator OVPN & PPP Dashboard Endpoint System")
        subtitle.setObjectName("pageSubtitle")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        row.addLayout(title_wrap)
        row.addStretch(1)
        return row

    def _build_cards(self):
        row = QHBoxLayout()
        row.setSpacing(12)
        self._cards = {
            "total": StatusCard("Total Connections", "0", "#2f93d1"),
            "active": StatusCard("Active Connections", "0", "#24d98b"),
            "failed": StatusCard("Failed Connections", "0", "#ff7a59"),
            "bandwidth": StatusCard("Bandwidth Usage", "0 Mbps", "#57a6ff"),
            "load": StatusCard("System Load", "0.00", "#8b5cf6"),
            "memory": StatusCard("Memory Usage", "0%", "#f59e0b"),
        }
        for card in self._cards.values():
            row.addWidget(card)
        return row

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contentCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_wrap = QVBoxLayout()
        label = QLabel("Connection Fleet")
        label.setObjectName("sectionTitle")
        caption = QLabel("OpenVPN, PPP, L2TP, and active tunnel throughput trends")
        caption.setObjectName("sectionCaption")
        title_wrap.addWidget(label)
        title_wrap.addWidget(caption)
        header.addLayout(title_wrap)
        header.addStretch(1)
        for text, handler in [
            ("Connect", self._connect_profile),
            ("Disconnect", self._disconnect_profile),
            ("Reconnect", self._reconnect_profile),
            ("Edit", self._edit_profile),
            ("Delete", self._delete_profile),
            ("Refresh", self.refresh),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            header.addWidget(button)
        layout.addLayout(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Quick filter connection table")
        layout.addWidget(self._search)

        self._table = QTableView()
        self._table.setModel(self._proxy_model)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(True)
        self._table.setItemDelegateForColumn(7, TrafficChartDelegate(self._table))
        self._table.setColumnWidth(0, 90)
        self._table.setColumnWidth(1, 240)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 150)
        self._table.setColumnWidth(4, 100)
        self._table.setColumnWidth(5, 110)
        self._table.setColumnWidth(6, 110)
        self._table.setColumnWidth(7, 150)
        self._table.setColumnWidth(8, 110)
        for row_index in range(12):
            self._table.setRowHeight(row_index, 56)
        layout.addWidget(self._table, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contentCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("Connection Inspector")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Tunnel IP, gateway, DNS, MTU, packet loss, routes, and speed fluctuation")
        subtitle.setObjectName("sectionCaption")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self._details_stack = QStackedWidget()
        empty = QLabel("Select a VPN connection to inspect traffic fluctuation, tunnel state, routes, DNS, and logs.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setObjectName("emptyState")
        self._details_stack.addWidget(empty)
        self._details_stack.addWidget(self._inspector)
        layout.addWidget(self._details_stack, 1)
        return panel

    def _build_bottom_dock(self) -> None:
        dock = QDockWidget("Logs, Terminal And SSH Mappings", self)
        self._bottom_dock = dock
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        tabs = QTabWidget()
        tabs.addTab(self._log_viewer, "Activity Log")
        tabs.addTab(self._terminal_panel, "Terminal")
        tabs.addTab(self._port_mapping_panel, "SSH Port Mapping")
        self._bottom_tabs = tabs
        dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _wire_signals(self) -> None:
        self._search.textChanged.connect(self._proxy_model.setFilterFixedString)
        self._global_search.textChanged.connect(self._proxy_model.setFilterFixedString)
        self._table.selectionModel().selectionChanged.connect(self._selection_changed)
        self._inspector.route_add_requested.connect(self._add_route)
        self._inspector.route_delete_requested.connect(self._delete_route)
        self._inspector.route_metric_change_requested.connect(self._change_metric)
        self._port_mapping_panel.status_message.connect(
            lambda message: self.statusBar().showMessage(message, 6000)
        )

    def refresh(self) -> None:
        if self._shutting_down:
            return
        try:
            stats = self._control_center_service.get_dashboard_stats()
            self._cards["total"].set_value(str(stats.total_connections))
            self._cards["active"].set_value(str(stats.active_connections))
            self._cards["failed"].set_value(str(stats.failed_connections))
            self._cards["bandwidth"].set_value(f"{stats.bandwidth_usage_mbps:.2f} Mbps")
            self._cards["load"].set_value(f"{stats.system_load:.2f}")
            self._cards["memory"].set_value(f"{stats.memory_usage_percent:.2f}%")
            rows = self._control_center_service.list_connection_rows()
            self._table_model.set_rows(rows)
            for row_index in range(len(rows)):
                self._table.setRowHeight(row_index, 56)
            self._log_viewer.replace_entries(self._control_center_service.list_logs(limit=200))
            self._port_mapping_panel.refresh()
            if self._selected_profile_id:
                self._load_inspector(self._selected_profile_id)
            if self._monitoring_error_reported:
                self.statusBar().showMessage("Monitoring recovered.", 3000)
                self._monitoring_error_reported = False
        except Exception as exc:
            if not self._monitoring_error_reported:
                LOGGER.exception("Dashboard refresh failed")
                self.statusBar().showMessage("Monitoring temporarily unavailable: " + self._safe_error(exc), 5000)
                self._monitoring_error_reported = True

    def _selection_changed(self) -> None:
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            self._selected_profile_id = None
            self._details_stack.setCurrentIndex(0)
            self._inspector.set_inspector(None)
            return
        source_index = self._proxy_model.mapToSource(indexes[0])
        profile_id = self._table_model.profile_id_at(source_index.row())
        self._selected_profile_id = profile_id
        if profile_id:
            self._load_inspector(profile_id)

    def _load_inspector(self, profile_id: str) -> None:
        try:
            inspector = self._control_center_service.get_connection_inspector(profile_id)
        except Exception as exc:
            LOGGER.exception("Connection inspector refresh failed")
            self._inspector.set_inspector(None)
            self._details_stack.setCurrentIndex(0)
            self.statusBar().showMessage("Inspector unavailable: " + self._safe_error(exc), 5000)
            return
        self._inspector.set_inspector(inspector)
        self._details_stack.setCurrentIndex(1 if inspector else 0)

    def _add_profile(self) -> None:
        dialog = ProfileDialog()
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            profile = self._control_center_service.save_profile(dialog.to_input())
        except ValueError as exc:
            self._show_operation_error("Invalid Connection Profile", exc)
            return
        except Exception as exc:
            LOGGER.exception("Manual profile creation failed")
            self._show_operation_error("Profile Save Error", exc)
            return
        self.statusBar().showMessage(f"Saved profile '{profile.name}'.", 5000)
        self.refresh()

    def _edit_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        dialog = ProfileDialog(profile)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            updated = self._control_center_service.save_profile(dialog.to_input(), profile.id)
        except ValueError as exc:
            self._show_operation_error("Invalid Connection Profile", exc)
            return
        except Exception as exc:
            LOGGER.exception("Profile update failed")
            self._show_operation_error("Profile Save Error", exc)
            return
        self.statusBar().showMessage(f"Updated profile '{updated.name}'.", 5000)
        self.refresh()

    def _delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            result = self._control_center_service.delete_profile(profile.id)
        except Exception as exc:
            LOGGER.exception("Profile deletion failed")
            self._show_operation_error("Profile Delete Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _connect_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            result = self._control_center_service.connect_profile(profile.id)
        except Exception as exc:
            LOGGER.exception("connect_profile failed")
            self._show_operation_error("Connection Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _disconnect_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            result = self._control_center_service.disconnect_profile(profile.id)
        except Exception as exc:
            LOGGER.exception("disconnect_profile failed")
            self._show_operation_error("Disconnect Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _reconnect_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        try:
            result = self._control_center_service.reconnect_profile(profile.id)
        except Exception as exc:
            LOGGER.exception("reconnect_profile failed")
            self._show_operation_error("Reconnect Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _import_ovpn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import OpenVPN Profile",
            str(Path.home()),
            "OpenVPN Files (*.ovpn *.conf *.txt);;All Files (*)",
        )
        if not path:
            return
        alias, ok = QInputDialog.getText(self, "OpenVPN Alias", "Alias")
        if not ok or not alias.strip():
            return
        try:
            preview = self._control_center_service.preview_ovpn_import(Path(path), alias.strip())
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return
        preview_errors = [str(item) for item in preview.get("errors", []) if str(item).strip()]
        if preview_errors:
            QMessageBox.critical(self, "Import Error", "\n".join(preview_errors))
            return
        username = str(preview.get("username") or "").strip()
        password = None
        if bool(preview.get("auth_user_pass_required")) and not preview.get("auth_user_pass_file"):
            username, ok = QInputDialog.getText(self, "OpenVPN Credentials", "Username", text=username)
            if not ok or not username.strip():
                return
            password, ok = QInputDialog.getText(
                self,
                "OpenVPN Credentials",
                "Password",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not password:
                return
        try:
            result = self._control_center_service.import_ovpn(
                Path(path),
                alias.strip(),
                username.strip() or None,
                password,
            )
        except Exception as exc:
            LOGGER.exception("OpenVPN import failed")
            self._show_operation_error("Import Error", exc)
            return
        self._show_import_result(result)
        self.refresh()

    def _add_route(self) -> None:
        destination, ok = QInputDialog.getText(self, "Add Route", "Destination CIDR or 'default'")
        if not ok or not destination.strip():
            return
        gateway, _ = QInputDialog.getText(self, "Add Route", "Gateway (optional)")
        metric, _ = QInputDialog.getInt(self, "Add Route", "Metric", 100, 1, 9999)
        device = None
        if self._selected_profile_id:
            inspector = self._control_center_service.get_connection_inspector(self._selected_profile_id)
            if inspector and inspector.row.interface_name != "-":
                device = inspector.row.interface_name
        try:
            result = self._control_center_service.add_route(destination.strip(), gateway.strip() or None, device, metric)
        except Exception as exc:
            LOGGER.exception("Route add failed")
            self._show_operation_error("Route Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _delete_route(self, destination: str, table: str) -> None:
        try:
            result = self._control_center_service.delete_route(destination, None if table == "-" else table)
        except Exception as exc:
            LOGGER.exception("Route deletion failed")
            self._show_operation_error("Route Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _change_metric(self, destination: str, gateway: str, device: str, table: str) -> None:
        metric, ok = QInputDialog.getInt(self, "Change Route Metric", "Metric", 100, 1, 9999)
        if not ok:
            return
        try:
            result = self._control_center_service.change_route_metric(
                destination,
                metric,
                None if gateway == "-" else gateway,
                None if device == "-" else device,
                None if table == "-" else table,
            )
        except Exception as exc:
            LOGGER.exception("Route metric change failed")
            self._show_operation_error("Route Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def shutdown(self):
        """Stop timers and all managed network sessions exactly once."""
        if self._shutting_down:
            return None
        self._shutting_down = True
        self._timer.stop()
        self._status_animation_timer.stop()
        try:
            result = self._control_center_service.shutdown()
        except Exception as exc:
            LOGGER.exception("KOPDES shutdown failed")
            return self._show_operation_error("Shutdown Error", exc, popup=False)
        if not result.success:
            LOGGER.error("KOPDES shutdown completed with failures: %s", result.details or result.message)
        return result

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        event.accept()

    def _selected_profile(self):
        if not self._selected_profile_id:
            QMessageBox.information(self, "KOPDES", "Select a connection first.")
            return None
        try:
            return self._control_center_service.get_profile(self._selected_profile_id)
        except Exception as exc:
            LOGGER.exception("Could not load selected profile")
            self._show_operation_error("Profile Error", exc)
            return None

    def _show_operation_error(self, title: str, error: Exception, popup: bool = True):
        message = self._safe_error(error)
        if popup:
            QMessageBox.critical(self, title, message)
        self.statusBar().showMessage(message, 8000)

    def _safe_error(self, error: Exception) -> str:
        detail = str(error).strip()
        return detail or error.__class__.__name__

    def _show_import_result(self, result) -> None:
        if result.success:
            message = "\n\n".join(part for part in [result.message, result.details] if part)
            QMessageBox.information(self, "Import Result", message)
            self.statusBar().showMessage(result.message, 6000)
            return
        QMessageBox.warning(self, "Import Error", "\n".join(part for part in [result.message, result.details] if part))

    def _show_result(self, result) -> None:
        if result.success:
            self.statusBar().showMessage(result.message, 6000)
            return
        QMessageBox.warning(self, "KOPDES", "\n".join(part for part in [result.message, result.details] if part))

    def _apply_window_icon(self) -> None:
        if self._logo_path.exists():
            self.setWindowIcon(QIcon(str(self._logo_path)))

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #0c1117;
                color: #dce7f1;
                font-size: 12px;
            }
            QFrame#navCard, QFrame#contentCard {
                background-color: #11161d;
                border: 1px solid #1b2632;
                border-radius: 18px;
            }
            QLabel#navLogo {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 21px;
                background-color: #13202b;
                border: 1px solid #234154;
                color: #27e08a;
                font-size: 20px;
                font-weight: 800;
            }
            QLabel#brandLabel {
                font-size: 22px;
                font-weight: 800;
                color: #f0f7ff;
            }
            QLabel#pageSubtitle, QLabel#sectionCaption {
                color: #7f96aa;
            }
            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: 700;
                color: #eef7ff;
            }
            QLabel#emptyState {
                color: #7f96aa;
                font-size: 15px;
            }
            QPushButton {
                background-color: #18212b;
                border: 1px solid #24313f;
                border-radius: 10px;
                padding: 8px 12px;
                color: #d8e3ee;
            }
            QPushButton:hover {
                background-color: #1f2b37;
            }
            QPushButton#primaryButton {
                background-color: #27e08a;
                color: #04120a;
                border: none;
                font-weight: 700;
            }
            QTableView, QTextEdit, QLineEdit, QTabWidget::pane {
                background-color: #121a24;
                border: 1px solid #202d3a;
                border-radius: 12px;
            }
            QTableView {
                alternate-background-color: #0f151d;
                selection-background-color: #1a3343;
            }
            QHeaderView::section {
                background-color: #141d28;
                color: #88a6bf;
                padding: 8px;
                border: none;
                font-weight: 600;
            }
            QLineEdit {
                padding: 10px 12px;
            }
            QDockWidget::title {
                background-color: #11161d;
                padding: 8px;
            }
            """
        )
