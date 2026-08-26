from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
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


LOGGER = logging.getLogger(__name__)


class PortMappingPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, service: ControlCenterService) -> None:
        super().__init__()
        self._service = service
        self._model = PortMappingTableModel()
        self._table = QTableView()
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
        try:
            self._model.set_rows(self._service.list_port_mapping_rows())
        except Exception as exc:
            LOGGER.exception("SSH mapping panel refresh failed")
            self._model.set_rows([])
            self.status_message.emit(f"SSH mapping monitoring unavailable: {self._safe_error(exc)}")

    def _selected_mapping_id(self) -> str | None:
        index = self._table.selectionModel().currentIndex()
        if not index.isValid():
            QMessageBox.information(self, "KOPDES", "Select an SSH port mapping first.")
            return None
        return self._model.mapping_id_at(index.row())

    def _add_mapping(self) -> None:
        dialog = PortMappingDialog(parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            mapping = self._service.save_port_mapping(dialog.to_input())
        except ValueError as exc:
            self._show_error("Invalid SSH Mapping", exc)
            return
        except Exception as exc:
            LOGGER.exception("SSH mapping creation failed")
            self._show_error("SSH Mapping Save Error", exc)
            return
        self.status_message.emit(f"Saved SSH mapping '{mapping.name}'.")
        self.refresh()

    def _edit_mapping(self) -> None:
        mapping_id = self._selected_mapping_id()
        if not mapping_id:
            return
        try:
            mapping = self._service.get_port_mapping(mapping_id)
        except Exception as exc:
            self._show_error("SSH Mapping Error", exc)
            return
        if mapping is None:
            self._show_error("SSH Mapping Error", ValueError("Selected SSH mapping no longer exists."))
            self.refresh()
            return
        dialog = PortMappingDialog(mapping, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            updated = self._service.save_port_mapping(dialog.to_input(), mapping.id)
        except ValueError as exc:
            self._show_error("Invalid SSH Mapping", exc)
            return
        except Exception as exc:
            LOGGER.exception("SSH mapping update failed")
            self._show_error("SSH Mapping Save Error", exc)
            return
        self.status_message.emit(f"Updated SSH mapping '{updated.name}'.")
        self.refresh()

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
        try:
            result = self._service.delete_port_mapping(mapping_id)
        except Exception as exc:
            LOGGER.exception("SSH mapping deletion failed")
            self._show_error("SSH Mapping Delete Error", exc)
            return
        self._show_result(result)
        self.refresh()

    def _run_action(self, method_name: str, error_title: str, success_prefix: str) -> None:
        mapping_id = self._selected_mapping_id()
        if not mapping_id:
            return
        try:
            result = getattr(self._service, method_name)(mapping_id)
        except Exception as exc:
            LOGGER.exception("SSH mapping action %s failed", method_name)
            self._show_error(error_title, exc)
            return
        self._show_result(result)
        if result.success:
            self.status_message.emit(f"{success_prefix}: {result.message}")
        self.refresh()

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
