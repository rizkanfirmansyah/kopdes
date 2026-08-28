from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
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
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.ui.dialogs.port_mapping_dialog import PortMappingDialog
from kopdes.ui.dialogs.profile_dialog import ProfileDialog
from kopdes.ui.operation_controller import OperationController
from kopdes.ui.pages import (
    ConnectionsPage,
    DiagnosticsPage,
    LogsPage,
    NetworkPage,
    OverviewPage,
    ProfilesPage,
    SettingsPage,
    SshTunnelsPage,
)
from kopdes.ui.widgets.log_viewer import LogViewer
from kopdes.ui.widgets.terminal_panel import TerminalPanel


LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Qt shell that keeps UI orchestration separate from Linux managers."""

    PAGE_TITLES = (
        "Overview",
        "Connections",
        "SSH Tunnels",
        "VPN Profiles",
        "Network",
        "Logs",
        "Diagnostics",
        "Settings",
    )

    def __init__(
        self,
        control_center_service: ControlCenterService,
        terminal_panel: TerminalPanel,
        refresh_interval_ms: int,
        data_dir: Path | None = None,
        database_url: str | None = None,
    ) -> None:
        super().__init__()
        self._service = control_center_service
        self._terminal = terminal_panel
        self._refresh_interval_ms = max(int(refresh_interval_ms), 500)
        self._data_dir = data_dir
        self._database_url = database_url
        self._operations = OperationController(self, max_threads=4)
        self._selected_profile_id: str | None = None
        self._profile_cache: dict[str, object] = {}
        self._row_cache: dict[str, object] = {}
        self._shutting_down = False
        self._shutdown_complete = False
        self._data_revision = 0
        self._last_auto_recovery_request = 0.0
        self._monitoring_error_reported = False
        self._logo_path = Path(__file__).resolve().parents[4] / "logo.png"

        self.setWindowTitle("KOPDES")
        self.setMinimumSize(980, 640)
        self.resize(1680, 980)
        self._apply_window_icon()
        self._build_ui()

        self._dashboard_timer = QTimer(self)
        self._dashboard_timer.timeout.connect(self._refresh_dashboard)
        self._dashboard_timer.start(self._refresh_interval_ms)
        self._network_timer = QTimer(self)
        self._network_timer.timeout.connect(self._refresh_network)
        self._network_timer.start(max(self._refresh_interval_ms, 1500))
        self._inspector_timer = QTimer(self)
        self._inspector_timer.timeout.connect(self._refresh_inspector)
        self._inspector_timer.start(max(self._refresh_interval_ms, 2000))
        QTimer.singleShot(0, self.refresh)

    def _build_ui(self) -> None:
        self._create_pages()
        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(14, 14, 14, 14)
        shell.setSpacing(14)
        shell.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        content_layout.addWidget(self._build_topbar())
        self._stack = QStackedWidget()
        for page in self._pages:
            self._stack.addWidget(page)
        content_layout.addWidget(self._stack, 1)
        shell.addWidget(content, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self._build_bottom_dock()
        self._wire_signals()
        self._apply_style()
        self._select_page(0)

    def _create_pages(self) -> None:
        self._overview = OverviewPage()
        self._connections = ConnectionsPage()
        self._ssh = SshTunnelsPage()
        self._profiles_page = ProfilesPage()
        self._network = NetworkPage()
        self._logs = LogsPage()
        self._diagnostics = DiagnosticsPage()
        self._settings = SettingsPage(
            self._data_dir,
            self._database_url,
            self._refresh_interval_ms,
        )
        self._pages = (
            self._overview,
            self._connections,
            self._ssh,
            self._profiles_page,
            self._network,
            self._logs,
            self._diagnostics,
            self._settings,
        )

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(260)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("sidebarLogo")
        if self._logo_path.is_file():
            logo.setPixmap(
                QPixmap(str(self._logo_path)).scaled(
                    38,
                    38,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            logo.setText("K")
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        title = QLabel("KOPDES")
        title.setObjectName("brandLabel")
        subtitle = QLabel("NETWORK OPS")
        subtitle.setObjectName("sidebarCaption")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text)
        layout.addLayout(brand)

        node = QLabel("CORE_NODE_01\nLOCAL CONTROL PLANE")
        node.setObjectName("nodeLabel")
        layout.addWidget(node)
        layout.addSpacing(14)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        nav_items = (
            ("Overview", "OV"),
            ("Connections", "CN"),
            ("SSH Tunnels", "SSH"),
            ("VPN Profiles", "VPN"),
            ("Network", "NET"),
            ("Logs", "LOG"),
            ("Diagnostics", "DIA"),
            ("Settings", "CFG"),
        )
        for index, (label, code) in enumerate(nav_items):
            button = QPushButton(f"{code:<4} {label}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            self._nav_group.addButton(button, index)
            layout.addWidget(button)
        layout.addStretch(1)
        footer = QLabel("SYSTEM READY\nManaged processes only")
        footer.setObjectName("sidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._page_title = QLabel("Overview")
        self._page_title.setObjectName("pageTitle")
        self._page_context = QLabel("Live operational view")
        self._page_context.setObjectName("mutedLabel")
        text.addWidget(self._page_title)
        text.addWidget(self._page_context)
        layout.addLayout(text, 1)

        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText(
            "Search connections, servers, tunnels, or errors"
        )
        self._global_search.setMinimumWidth(260)
        layout.addWidget(self._global_search)
        self._terminal_button = QPushButton("Terminal")
        self._terminal_button.setCheckable(True)
        layout.addWidget(self._terminal_button)
        self._quick_add_button = QPushButton("+ Add New")
        self._quick_add_button.setObjectName("primaryButton")
        self._quick_add_button.clicked.connect(self._quick_add)
        layout.addWidget(self._quick_add_button)
        return bar

    def _build_bottom_dock(self) -> None:
        self._activity_log = LogViewer()
        tabs = QTabWidget()
        tabs.addTab(self._activity_log, "Activity")
        tabs.addTab(self._terminal, "Terminal")
        dock = QDockWidget("Operations Console", self)
        dock.setObjectName("operationsDock")
        dock.setWidget(tabs)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._bottom_dock = dock
        self._bottom_tabs = tabs
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.visibilityChanged.connect(self._terminal_button.setChecked)
        self._terminal_button.setChecked(True)

    def _wire_signals(self) -> None:
        self._nav_group.idClicked.connect(self._select_page)
        self._stack.currentChanged.connect(self._page_changed)
        self._global_search.textChanged.connect(self._apply_global_filter)
        self._terminal_button.toggled.connect(self._toggle_terminal)

        self._overview.connections_requested.connect(lambda: self._select_page(1))
        self._overview.ssh_requested.connect(lambda: self._select_page(2))
        self._overview.refresh_requested.connect(self.refresh)

        self._connections.profile_selected.connect(self._profile_selected)
        self._connections.connect_requested.connect(self._connect_profile)
        self._connections.disconnect_requested.connect(self._disconnect_profile)
        self._connections.reconnect_requested.connect(self._reconnect_profile)
        self._connections.edit_requested.connect(self._edit_profile)
        self._connections.delete_requested.connect(self._delete_profile)
        self._connections.add_requested.connect(self._add_profile)
        self._connections.import_requested.connect(self._import_ovpn)
        self._connections.refresh_requested.connect(self.refresh)
        self._connections.route_add_requested.connect(self._add_route)
        self._connections.route_delete_requested.connect(self._delete_route)
        self._connections.route_metric_change_requested.connect(self._change_route_metric)

        self._ssh.add_requested.connect(self._add_mapping)
        self._ssh.edit_requested.connect(self._edit_mapping)
        self._ssh.connect_requested.connect(self._connect_mapping)
        self._ssh.disconnect_requested.connect(self._disconnect_mapping)
        self._ssh.delete_requested.connect(self._delete_mapping)
        self._ssh.refresh_requested.connect(self.refresh)

        self._profiles_page.profile_selected.connect(self._profile_selected)
        self._profiles_page.add_requested.connect(self._add_profile)
        self._profiles_page.import_requested.connect(self._import_ovpn)
        self._profiles_page.edit_requested.connect(self._edit_profile)
        self._profiles_page.delete_requested.connect(self._delete_profile)
        self._profiles_page.refresh_requested.connect(self.refresh)

        self._network.refresh_requested.connect(self._refresh_network)
        self._network.route_add_requested.connect(self._add_route)
        self._network.route_delete_requested.connect(self._delete_route)
        self._network.route_metric_change_requested.connect(self._change_route_metric)
        self._logs.refresh_requested.connect(self._refresh_dashboard)
        self._logs.export_requested.connect(self._export_logs)
        self._diagnostics.run_requested.connect(self._run_diagnostic)

    def _select_page(self, index: int) -> None:
        if not 0 <= int(index) < len(self.PAGE_TITLES):
            return
        index = int(index)
        self._stack.setCurrentIndex(index)
        button = self._nav_group.button(index)
        if button is not None:
            button.setChecked(True)

    def _page_changed(self, index: int) -> None:
        title = self.PAGE_TITLES[index]
        self._page_title.setText(title)
        self._page_context.setText(
            {
                0: "Live operational view",
                1: "Session state and tunnel telemetry",
                2: "Explicitly owned SSH forwarding processes",
                3: "Encrypted VPN and PPP configuration",
                4: "Interfaces, routes, rules, and DNS",
                5: "Structured application activity",
                6: "Bounded network diagnostics",
                7: "Runtime paths and safety policies",
            }.get(index, "KOPDES")
        )
        self._quick_add_button.setVisible(index in {1, 2, 3})

    def _toggle_terminal(self, visible: bool) -> None:
        self._bottom_dock.setVisible(visible)
        if visible:
            self._bottom_tabs.setCurrentIndex(1)

    def _quick_add(self) -> None:
        index = self._stack.currentIndex()
        if index == 2:
            self._add_mapping()
            return
        if index == 3:
            self._add_profile()
            return
        self._select_page(1)
        self._add_profile()

    def _apply_global_filter(self, text: str) -> None:
        self._connections.set_global_filter(text)
        self._ssh.set_global_filter(text)
        self._profiles_page.set_global_filter(text)
        self._logs.set_global_filter(text)

    def refresh(self) -> None:
        if self._shutting_down:
            return
        self._refresh_dashboard()
        self._refresh_network()
        self._refresh_inspector()

    def _refresh_dashboard(self) -> None:
        revision = self._data_revision
        self._submit(
            "dashboard",
            lambda: self._service.get_dashboard_snapshot(log_limit=300),
            lambda snapshot, expected=revision: self._apply_dashboard(expected, snapshot),
            self._monitoring_error,
        )

    def _apply_dashboard(self, expected_revision: int, snapshot) -> None:
        if expected_revision != self._data_revision:
            return
        self._profile_cache = {
            profile.id: profile for profile in snapshot.profiles
        }
        self._row_cache = {row.profile_id: row for row in snapshot.rows}
        self._overview.set_snapshot(snapshot.stats, snapshot.rows, snapshot.logs, snapshot.port_mapping_rows)
        self._connections.set_rows(snapshot.rows)
        self._profiles_page.set_profiles(
            snapshot.profiles,
            {row.profile_id: row.status for row in snapshot.rows},
        )
        self._ssh.set_rows(snapshot.port_mapping_rows)
        self._activity_log.replace_entries(snapshot.logs)
        self._logs.set_logs(snapshot.logs)
        if self._monitoring_error_reported:
            self.statusBar().showMessage("Monitoring recovered.", 3000)
            self._monitoring_error_reported = False
        if self._selected_profile_id not in self._profile_cache:
            self._selected_profile_id = None
            self._connections.set_inspector(None)
        self._schedule_auto_recovery(snapshot)

    def _schedule_auto_recovery(self, snapshot) -> None:
        if self._shutting_down or self._operations.is_running("auto-recovery"):
            return
        if not any(
            profile.auto_reconnect
            and any(
                row.profile_id == profile.id and row.status.value == "failed"
                for row in snapshot.rows
            )
            for profile in snapshot.profiles
        ):
            return
        now = monotonic()
        if now - self._last_auto_recovery_request < 2.0:
            return
        self._last_auto_recovery_request = now
        self._submit(
            "auto-recovery",
            self._service.recover_failed_connections,
            self._auto_recovery_finished,
            self._monitoring_error,
        )

    def _auto_recovery_finished(self, result) -> None:
        attempted = getattr(result, "data", {}).get("attempted", "0")
        if attempted != "0":
            self.statusBar().showMessage(result.message, 5000)
            self.refresh()

    def _refresh_network(self) -> None:
        if self._shutting_down:
            return
        revision = self._data_revision
        self._submit(
            "network",
            self._service.get_network_snapshot,
            lambda snapshot, expected=revision: self._apply_network(expected, snapshot),
            self._monitoring_error,
        )

    def _apply_network(self, expected_revision: int, snapshot) -> None:
        if expected_revision == self._data_revision:
            self._network.set_snapshot(snapshot)

    def _refresh_inspector(self) -> None:
        if self._shutting_down or self._stack.currentIndex() != 1:
            return
        profile_id = self._selected_profile_id
        if not profile_id:
            self._connections.set_inspector(None)
            return
        revision = self._data_revision
        self._submit(
            "inspector",
            lambda: self._service.get_connection_inspector(profile_id),
            lambda inspector, expected=profile_id, expected_revision=revision: self._apply_inspector(
                expected_revision,
                expected,
                inspector,
            ),
            self._monitoring_error,
        )

    def _apply_inspector(self, revision: int, profile_id: str, inspector) -> None:
        if revision == self._data_revision and profile_id == self._selected_profile_id:
            self._connections.set_inspector(inspector)

    def _profile_selected(self, profile_id: str) -> None:
        self._selected_profile_id = profile_id or None
        self._refresh_inspector()

    def _selected_profile(self, profile_id: str | None = None):
        selected_id = profile_id or self._selected_profile_id
        profile = self._profile_cache.get(selected_id) if selected_id else None
        if profile is None:
            self.statusBar().showMessage("Select a connection first.", 4000)
        return profile

    def _add_profile(self) -> None:
        dialog = ProfileDialog()
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            data = dialog.to_input()
        except Exception as exc:
            self._show_error("Invalid Connection Profile", exc)
            return
        self._submit(
            "profile-save",
            lambda: self._service.save_profile(data),
            lambda profile: self._profile_saved(profile, "Saved"),
            lambda error: self._show_error("Profile Save Error", error),
        )

    def _edit_profile(self, profile_id: str | None = None) -> None:
        profile = self._selected_profile(profile_id)
        if profile is None:
            return
        dialog = ProfileDialog(profile)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            data = dialog.to_input()
        except Exception as exc:
            self._show_error("Invalid Connection Profile", exc)
            return
        self._submit(
            "profile-save",
            lambda: self._service.save_profile(data, profile.id),
            lambda saved: self._profile_saved(saved, "Updated"),
            lambda error: self._show_error("Profile Save Error", error),
        )

    def _profile_saved(self, profile, action: str) -> None:
        self.statusBar().showMessage(f"{action} profile '{profile.name}'.", 5000)
        self.refresh()

    def _delete_profile(self, profile_id: str | None = None) -> None:
        profile = self._selected_profile(profile_id)
        if profile is None:
            return
        if not self._confirm(
            "Delete Connection Profile",
            f"Delete '{profile.name}' and its managed runtime profile?",
        ):
            return
        self._connections.set_action_state(profile.id, "delete")
        submitted = self._submit(
            f"profile-action:{profile.id}",
            lambda: self._service.delete_profile(profile.id),
            lambda result: self._profile_action_finished(
                profile.id,
                "delete",
                result,
            ),
            lambda error: self._profile_action_failed(profile.id, "delete", error),
        )
        if not submitted:
            self._connections.set_action_state(profile.id, None)

    def _connect_profile(self, profile_id: str) -> None:
        self._run_profile_action(profile_id, "connect", self._service.connect_profile)

    def _disconnect_profile(self, profile_id: str) -> None:
        self._run_profile_action(profile_id, "disconnect", self._service.disconnect_profile)

    def _reconnect_profile(self, profile_id: str) -> None:
        self._run_profile_action(profile_id, "reconnect", self._service.reconnect_profile)

    def _run_profile_action(self, profile_id: str, operation: str, method) -> None:
        if self._selected_profile(profile_id) is None:
            return
        key = f"profile-action:{profile_id}"
        if self._operations.is_running(key):
            return
        self._connections.set_action_state(profile_id, operation)
        self.statusBar().showMessage(f"{operation.upper()} in progress...", 3000)
        submitted = self._submit(
            key,
            lambda: method(profile_id),
            lambda result: self._profile_action_finished(
                profile_id,
                operation,
                result,
            ),
            lambda error: self._profile_action_failed(profile_id, operation, error),
        )
        if not submitted:
            self._connections.set_action_state(profile_id, None)

    def _profile_action_finished(self, profile_id: str, operation: str, result) -> None:
        self._connections.set_action_state(profile_id, None)
        self._show_result(result)
        self.refresh()

    def _profile_action_failed(
        self,
        profile_id: str,
        operation: str,
        error: Exception,
    ) -> None:
        self._connections.set_action_state(profile_id, None)
        self._show_error(f"{operation.title()} Error", error)
        self.refresh()

    def _import_ovpn(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Import OpenVPN Profile",
            str(Path.home()),
            "OpenVPN Files (*.ovpn *.conf *.txt);;All Files (*)",
        )
        if not path_text:
            return
        alias, ok = QInputDialog.getText(self, "OpenVPN Alias", "Alias")
        if not ok or not alias.strip():
            return
        path = Path(path_text).expanduser()
        alias = alias.strip()
        self.statusBar().showMessage(f"Parsing '{path.name}'...", 5000)
        self._submit(
            "ovpn-preview",
            lambda: self._service.preview_ovpn_import(path, alias),
            lambda preview: self._ovpn_preview_ready(path, alias, preview),
            lambda error: self._show_error("OpenVPN Import Error", error),
        )

    def _ovpn_preview_ready(
        self,
        path: Path,
        alias: str,
        preview: dict[str, object],
    ) -> None:
        errors = [
            str(item) for item in preview.get("errors", []) if str(item).strip()
        ]
        if errors:
            self._show_message(
                "OpenVPN Import Error",
                "\n".join(errors),
                critical=True,
            )
            return
        warnings = [
            str(item) for item in preview.get("warnings", []) if str(item).strip()
        ]
        username = str(preview.get("username") or "").strip()
        password = None
        if (
            bool(preview.get("auth_user_pass_required"))
            and not preview.get("auth_user_pass_file")
        ):
            username, ok = QInputDialog.getText(
                self,
                "OpenVPN Credentials",
                "Username",
                text=username,
            )
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
        if warnings:
            self.statusBar().showMessage(
                "Import parsed with warnings: " + " | ".join(warnings),
                8000,
            )
        self._submit(
            "ovpn-import",
            lambda: self._service.import_ovpn(
                path,
                alias,
                username or None,
                password,
            ),
            self._ovpn_import_finished,
            lambda error: self._show_error("OpenVPN Import Error", error),
        )

    def _ovpn_import_finished(self, result) -> None:
        self._show_import_result(result)
        self.refresh()

    def _add_mapping(self) -> None:
        dialog = PortMappingDialog(parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            data = dialog.to_input()
        except Exception as exc:
            self._show_error("Invalid SSH Mapping", exc)
            return
        self._submit(
            "mapping-save",
            lambda: self._service.save_port_mapping(data),
            lambda mapping: self._mapping_saved(mapping, "Saved"),
            lambda error: self._show_error("SSH Mapping Save Error", error),
        )

    def _edit_mapping(self, mapping_id: str) -> None:
        self._submit(
            "mapping-load",
            lambda: self._service.get_port_mapping(mapping_id),
            self._mapping_loaded,
            lambda error: self._show_error("SSH Mapping Error", error),
        )

    def _mapping_loaded(self, mapping) -> None:
        if mapping is None:
            self._show_message(
                "SSH Mapping Error",
                "The selected mapping no longer exists.",
                critical=True,
            )
            self.refresh()
            return
        dialog = PortMappingDialog(mapping, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            data = dialog.to_input()
        except Exception as exc:
            self._show_error("Invalid SSH Mapping", exc)
            return
        self._submit(
            "mapping-save",
            lambda: self._service.save_port_mapping(data, mapping.id),
            lambda saved: self._mapping_saved(saved, "Updated"),
            lambda error: self._show_error("SSH Mapping Save Error", error),
        )

    def _mapping_saved(self, mapping, action: str) -> None:
        self.statusBar().showMessage(
            f"{action} SSH mapping '{mapping.name}'.",
            5000,
        )
        self.refresh()

    def _connect_mapping(self, mapping_id: str) -> None:
        self._run_mapping_action(
            mapping_id,
            "connect",
            self._service.connect_port_mapping,
        )

    def _disconnect_mapping(self, mapping_id: str) -> None:
        self._run_mapping_action(
            mapping_id,
            "disconnect",
            self._service.disconnect_port_mapping,
        )

    def _run_mapping_action(self, mapping_id: str, operation: str, method) -> None:
        key = f"mapping-action:{mapping_id}"
        if self._operations.is_running(key):
            return
        self._ssh.set_action_state(True, mapping_id)
        self.statusBar().showMessage(f"SSH {operation} in progress...", 3000)
        submitted = self._submit(
            key,
            lambda: method(mapping_id),
            lambda result: self._mapping_action_finished(mapping_id, operation, result),
            lambda error: self._mapping_action_failed(mapping_id, operation, error),
        )
        if not submitted:
            self._ssh.set_action_state(False, mapping_id)

    def _mapping_action_finished(self, mapping_id: str, operation: str, result) -> None:
        self._ssh.set_action_state(False, mapping_id)
        self._show_result(result)
        self.refresh()

    def _mapping_action_failed(self, mapping_id: str, operation: str, error: Exception) -> None:
        self._ssh.set_action_state(False, mapping_id)
        self._show_error(f"SSH {operation.title()} Error", error)
        self.refresh()

    def _delete_mapping(self, mapping_id: str) -> None:
        if not self._confirm(
            "Delete SSH Mapping",
            "Delete the selected mapping and stop its managed tunnel?",
        ):
            return
        self._ssh.set_action_state(True, mapping_id)
        submitted = self._submit(
            f"mapping-action:{mapping_id}",
            lambda: self._service.delete_port_mapping(mapping_id),
            lambda result: self._mapping_action_finished(mapping_id, "delete", result),
            lambda error: self._mapping_action_failed(mapping_id, "delete", error),
        )
        if not submitted:
            self._ssh.set_action_state(False, mapping_id)

    def _add_route(self) -> None:
        destination, ok = QInputDialog.getText(
            self,
            "Add Route",
            "Destination CIDR or 'default'",
        )
        if not ok or not destination.strip():
            return
        gateway, _ = QInputDialog.getText(self, "Add Route", "Gateway (optional)")
        metric, ok = QInputDialog.getInt(
            self,
            "Add Route",
            "Metric",
            100,
            1,
            9999,
        )
        if not ok:
            return
        device = None
        row = (
            self._row_cache.get(self._selected_profile_id)
            if self._selected_profile_id
            else None
        )
        if row and row.interface_name != "-":
            device = row.interface_name
        self._submit(
            "route-add",
            lambda: self._service.add_route(
                destination.strip(),
                gateway.strip() or None,
                device,
                metric,
            ),
            self._route_finished,
            lambda error: self._show_error("Route Error", error),
        )

    def _delete_route(self, destination: str, table: str) -> None:
        self._submit(
            "route-delete",
            lambda: self._service.delete_route(
                destination,
                None if table == "-" else table,
            ),
            self._route_finished,
            lambda error: self._show_error("Route Error", error),
        )

    def _change_route_metric(
        self,
        destination: str,
        gateway: str,
        device: str,
        table: str,
    ) -> None:
        metric, ok = QInputDialog.getInt(
            self,
            "Change Route Metric",
            "Metric",
            100,
            1,
            9999,
        )
        if not ok:
            return
        self._submit(
            "route-metric",
            lambda: self._service.change_route_metric(
                destination,
                metric,
                None if gateway == "-" else gateway,
                None if device == "-" else device,
                None if table == "-" else table,
            ),
            self._route_finished,
            lambda error: self._show_error("Route Error", error),
        )

    def _route_finished(self, result) -> None:
        self._show_result(result)
        self._refresh_network()

    def _run_diagnostic(self, check_type: str, target: str, timeout: int) -> None:
        self._diagnostics.set_running()
        submitted = self._submit(
            "diagnostic",
            lambda: self._service.run_health_check(check_type, target, timeout),
            self._diagnostics.set_result,
            self._diagnostic_failed,
        )
        if not submitted:
            self._diagnostics.set_error(
                RuntimeError("A diagnostic operation is already running.")
            )

    def _diagnostic_failed(self, error: Exception) -> None:
        self._diagnostics.set_error(error)
        self._show_error("Diagnostic Error", error)

    def _submit(self, key: str, operation, on_result, on_error) -> bool:
        read_only_keys = {
            "dashboard",
            "network",
            "inspector",
            "diagnostic",
            "ovpn-preview",
            "mapping-load",
            "logs-export",
        }
        submitted = self._operations.submit(key, operation, on_result, on_error)
        if submitted and key not in read_only_keys:
            self._data_revision += 1
        return submitted

    def _export_logs(self, path: str, content: str) -> None:
        self.statusBar().showMessage("Exporting logs...", 3000)
        submitted = self._submit(
            "logs-export",
            lambda: Path(path).write_text(content, encoding="utf-8"),
            lambda _result: self.statusBar().showMessage(
                f"Logs exported to {path}.",
                6000,
            ),
            lambda error: self._show_error("Log Export Error", error),
        )
        if not submitted:
            self._show_message(
                "Log Export Error",
                "Another log export is already running.",
                critical=False,
            )

    def _monitoring_error(self, error: Exception) -> None:
        if not self._monitoring_error_reported:
            LOGGER.error("Background monitoring failed: %s", error)
            self.statusBar().showMessage(
                "Monitoring temporarily unavailable: " + self._safe_error(error),
                6000,
            )
            self._monitoring_error_reported = True

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _show_result(self, result) -> None:
        if result.success:
            self.statusBar().showMessage(result.message, 6000)
            return
        self._show_message(
            "KOPDES Operation Failed",
            result.message,
            getattr(result, "details", None),
            critical=False,
        )

    def _show_import_result(self, result) -> None:
        if result.success:
            details = getattr(result, "details", None)
            if details and "Warnings:" in details:
                self._show_message(
                    "OpenVPN Import Completed With Warnings",
                    result.message,
                    details,
                )
            else:
                self.statusBar().showMessage(result.message, 7000)
            return
        self._show_message(
            "OpenVPN Import Failed",
            result.message,
            getattr(result, "details", None),
            critical=True,
        )

    def _show_error(self, title: str, error: Exception) -> None:
        message = self._safe_error(error)
        LOGGER.error("%s: %s", title, message)
        self._show_message(title, message, str(error), critical=True)

    def _show_message(
        self,
        title: str,
        message: str,
        details: str | None = None,
        critical: bool = False,
    ) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(
            QMessageBox.Icon.Critical if critical else QMessageBox.Icon.Warning
        )
        box.setText(message)
        if details and details.strip() and details.strip() != message.strip():
            box.setDetailedText(details)
        box.exec()
        self.statusBar().showMessage(message, 8000)

    def _safe_error(self, error: Exception) -> str:
        detail = str(error).strip()
        return detail.splitlines()[0] if detail else error.__class__.__name__

    def _apply_window_icon(self) -> None:
        if self._logo_path.is_file():
            self.setWindowIcon(QIcon(str(self._logo_path)))

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0f1416; color: #dce8e7; font-family: "Inter"; font-size: 12px; }
            QFrame#sidebar { background: #171d1e; border: 1px solid #283234; border-radius: 16px; }
            QFrame#topbar, QFrame#panel, QFrame#metricCard, QDockWidget { background: #171d1e; border: 1px solid #283234; border-radius: 14px; }
            QLabel#brandLabel { color: #f2fbf7; font-size: 20px; font-weight: 800; }
            QLabel#sidebarCaption, QLabel#mutedLabel, QLabel#panelSubtitle, QLabel#pageSubtitle { color: #829695; }
            QLabel#panelTitle { color: #f2fbf7; font-size: 14px; font-weight: 700; }
            QLabel#nodeLabel { background: #101718; color: #73e6b2; border: 1px solid #2b4940; border-radius: 9px; padding: 9px; font-family: "JetBrains Mono"; font-size: 10px; }
            QLabel#sidebarFooter { color: #73e6b2; background: #13231e; border: 1px solid #29483d; border-radius: 9px; padding: 9px; font-family: "JetBrains Mono"; font-size: 10px; }
            QLabel#sidebarLogo { min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; border-radius: 20px; background: #101718; border: 1px solid #34534a; color: #55d7ed; font-size: 20px; font-weight: 800; }
            QLabel#pageTitle { color: #f2fbf7; font-size: 22px; font-weight: 800; }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QTableView, QTableWidget, QTabWidget::pane { background: #101719; color: #dce8e7; border: 1px solid #293839; border-radius: 9px; }
            QLineEdit, QComboBox, QSpinBox { padding: 8px 10px; }
            QPushButton { background: #1c2728; color: #cfe0de; border: 1px solid #334345; border-radius: 8px; padding: 8px 12px; }
            QPushButton:hover { background: #263536; border-color: #55d7ed; }
            QPushButton:disabled { color: #60706f; background: #151c1d; }
            QPushButton#primaryButton, QPushButton[variant="primary"] { background: #73e6b2; color: #0b1714; border: none; font-weight: 700; }
            QPushButton[variant="danger"] { color: #ffb4ab; border-color: #74433f; }
            QPushButton#navButton { text-align: left; color: #93a9a7; border: none; background: transparent; padding: 11px 10px; font-family: "JetBrains Mono"; }
            QPushButton#navButton:hover { background: #202a2b; color: #dce8e7; }
            QPushButton#navButton:checked { background: #263536; color: #55d7ed; border-left: 3px solid #55d7ed; }
            QHeaderView::section { background: #1b2526; color: #8ca7a4; border: none; padding: 9px 8px; font-weight: 700; }
            QTableView { alternate-background-color: #131b1c; selection-background-color: #234247; selection-color: #f2fbf7; }
            QTableWidget { alternate-background-color: #131b1c; selection-background-color: #234247; }
            QTableView::item, QTableWidget::item { padding: 7px; }
            QPlainTextEdit, QTextEdit { font-family: "JetBrains Mono"; }
            QDockWidget::title { background: #1b2526; color: #dce8e7; padding: 8px 12px; }
            QTabBar::tab { background: #141d1e; color: #849b99; padding: 8px 14px; border: none; }
            QTabBar::tab:selected { color: #55d7ed; border-bottom: 2px solid #55d7ed; }
            QScrollBar:vertical { background: #101719; width: 10px; }
            QScrollBar::handle:vertical { background: #334345; border-radius: 5px; min-height: 24px; }
            """
        )

    def shutdown(self) -> None:
        """Begin bounded asynchronous shutdown; retained for external callers."""
        self._begin_shutdown()

    def _begin_shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._dashboard_timer.stop()
        self._network_timer.stop()
        self._inspector_timer.stop()
        self._terminal.shutdown()
        try:
            self._service.request_stop_all()
        except Exception:
            LOGGER.exception("Could not request managed process shutdown")
        self._operations.cancel_pending(discard_callbacks=True)
        submitted = self._operations.submit(
            "shutdown",
            self._service.shutdown,
            self._shutdown_finished,
            self._shutdown_failed,
        )
        self._operations.stop_accepting()
        if not submitted:
            self._force_shutdown()
            return
        self.statusBar().showMessage("Stopping managed connections...", 15000)
        QTimer.singleShot(15000, self._force_shutdown)

    def _shutdown_finished(self, result) -> None:
        if not result.success:
            LOGGER.error(
                "Shutdown completed with failures: %s",
                result.details or result.message,
            )
        self._finish_shutdown()

    def _shutdown_failed(self, error: Exception) -> None:
        LOGGER.error("KOPDES shutdown failed: %s", error)
        self._finish_shutdown()

    def _finish_shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        self._operations.shutdown()
        self.close()

    def _force_shutdown(self) -> None:
        if self._shutdown_complete:
            return
        LOGGER.error("KOPDES shutdown timed out; closing UI after bounded wait.")
        self._operations.shutdown()
        self._finish_shutdown()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutdown_complete:
            event.accept()
            return
        if not self._shutting_down:
            self._begin_shutdown()
        event.ignore()
