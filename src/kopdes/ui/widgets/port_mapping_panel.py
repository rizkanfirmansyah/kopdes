from __future__ import annotations

import logging

from PySide6.QtCore import QCloseEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.ui.dialogs.port_mapping_dialog import PortMappingDialog
from kopdes.ui.models.port_mapping_table_model import PortMappingTableModel
from kopdes.ui.operation_controller import OperationController


LOGGER = logging.getLogger(__name__)


class PortMappingPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, service: ControlCenterService) -> None:
        super().__init__()
        self._service = service
        self._model = PortMappingTableModel()
        self._table = QTableView()
        self._operations = OperationController(self, max_threads=2)
        self._closed = False
        self._build_ui()

    def _build_ui(self) -> None:
        container = QFrame()
        container.setObjectName("contentCard")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        actions = QHBoxLayout()
        for label, handler, object_name in (
            ("+ Add Mapping", self._add_mapping, "primaryButton"),
            ("Edit", self._edit_mapping, ""),
            ("Connect", self._connect_mapping, ""),
            ("Disconnect", self._disconnect_mapping, ""),
            ("Delete", self._delete_mapping, ""),
            ("Refresh", self.refresh, ""),
        ):
            button = QPushButton(label)
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._table.setModel(self._model)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.doubleClicked.connect(lambda _index: self._edit_mapping())
        for column, width in enumerate((110, 180, 150, 150, 260, 80, 100)):
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

    def refresh(self) -> None:
        if self._closed:
            return
        self._operations.submit(
            "mapping-refresh",
            self._service.list_port_mapping_rows,
            self._apply_rows,
            lambda error: self._operation_error("SSH Mapping Refresh Error", error),
        )

    def _apply_rows(self, rows) -> None:
        self._model.set_rows(rows)

    def _selected_mapping_id(self) -> str | None:
        index = self._table.selectionModel().currentIndex()
        if not index.isValid():
            QMessageBox.information(self, "KOPDES", "Select an SSH port mapping first.")
            return None
        return self._model.mapping_id_at(index.row())

    def add_mapping(self) -> None:
        self._add_mapping()

    def _add_mapping(self) -> None:
        dialog = PortMappingDialog(parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._submit_mapping_operation(
            "mapping-create",
            lambda: self._service.save_port_mapping(dialog.to_input()),
            lambda mapping: self._mapping_saved(mapping, "Saved"),
            "SSH Mapping Save Error",
        )

    def _edit_mapping(self) -> None:
        mapping_id = self._selected_mapping_id()
        if not mapping_id:
            return
        self._submit_mapping_operation(
            "mapping-load",
            lambda: self._service.get_port_mapping(mapping_id),
            self._edit_loaded,
            "SSH Mapping Error",
        )

    def _edit_loaded(self, mapping) -> None:
        if mapping is None:
            self._show_error("SSH Mapping Error", ValueError("Selected SSH mapping no longer exists."))
            self.refresh()
            return
        dialog = PortMappingDialog(mapping, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._submit_mapping_operation(
            "mapping-update",
            lambda: self._service.save_port_mapping(dialog.to_input(), mapping.id),
            lambda updated: self._mapping_saved(updated, "Updated"),
            "SSH Mapping Save Error",
        )

    def _connect_mapping(self) -> None:
        self._run_action("connect_port_mapping", "SSH Mapping Connection Error", "SSH mapping connected")

    def _disconnect_mapping(self) -> None:
        self._run_action("disconnect_port_mapping", "SSH Mapping Disconnect Error", "SSH mapping disconnected")

    def _delete_mapping(self) -> None:
        mapping_id = self._selected_mapping_id()
        if not mapping_id:
            return
        answer = QMessageBox.question(
            self,
            "Delete SSH Mapping",
            "Delete the selected mapping and stop its managed tunnel?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._submit_mapping_operation(
            "mapping-delete",
            lambda: self._service.delete_port_mapping(mapping_id),
            self._action_finished,
            "SSH Mapping Delete Error",
        )

    def _run_action(self, method_name: str, error_title: str, success_prefix: str) -> None:
        mapping_id = self._selected_mapping_id()
        if not mapping_id:
            return
        self._submit_mapping_operation(
            "mapping-action",
            lambda: getattr(self._service, method_name)(mapping_id),
            lambda result: self._action_finished(result, success_prefix),
            error_title,
        )

    def _submit_mapping_operation(self, key, operation, on_result, error_title) -> None:
        if not self._operations.submit(
            key,
            operation,
            on_result,
            lambda error: self._operation_error(error_title, error),
        ):
            self.status_message.emit("Another SSH mapping operation is already running.")

    def _mapping_saved(self, mapping, action: str) -> None:
        self.status_message.emit(f"{action} SSH mapping '{mapping.name}'.")
        QTimer.singleShot(0, self.refresh)

    def _action_finished(self, result, success_prefix: str = "") -> None:
        self._show_result(result)
        if success_prefix and result.success:
            self.status_message.emit(f"{success_prefix}: {result.message}")
        QTimer.singleShot(0, self.refresh)

    def _operation_error(self, title: str, error: Exception) -> None:
        LOGGER.error("%s: %s", title, error)
        self._show_error(title, error)

    def _show_result(self, result) -> None:
        if result.success:
            self.status_message.emit(result.message)
            return
        QMessageBox.warning(self, "KOPDES", "\n".join(part for part in [result.message, result.details] if part))

    def _show_error(self, title: str, error: Exception) -> None:
        message = self._safe_error(error)
        QMessageBox.critical(self, title, message)
        self.status_message.emit(message)

    def _safe_error(self, error: Exception) -> str:
        detail = str(error).strip()
        return detail or error.__class__.__name__

    def shutdown(self) -> None:
        self._closed = True
        self._operations.shutdown()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        event.accept()
