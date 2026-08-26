from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kopdes.application.dtos.connection_profile_dto import PortMappingInput
from kopdes.domain.entities.port_mapping import PortMapping


class PortMappingDialog(QDialog):
    def __init__(self, mapping: PortMapping | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH Local Port Mapping")
        self.resize(560, 680)
        self._mapping = mapping

        self._name = QLineEdit(mapping.name if mapping else "")
        self._description = QPlainTextEdit(mapping.description if mapping else "")
        self._ssh_host = QLineEdit(mapping.ssh_host if mapping else "")
        self._ssh_port = self._spin(1, 65535, mapping.ssh_port if mapping else 22)
        self._ssh_username = QLineEdit(mapping.ssh_username if mapping else "")
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Leave blank to keep the saved password")
        self._identity_file = QLineEdit(mapping.identity_file if mapping and mapping.identity_file else "")
        self._identity_file.setPlaceholderText("Optional; prefer an SSH key or agent")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_identity)
        identity_row = QWidget()
        identity_layout = QHBoxLayout(identity_row)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.addWidget(self._identity_file, 1)
        identity_layout.addWidget(browse)

        self._local_host = QLineEdit(mapping.local_host if mapping else "127.0.0.1")
        self._local_port = self._spin(1024, 65535, mapping.local_port if mapping else 5433)
        self._remote_host = QLineEdit(mapping.remote_host if mapping else "127.0.0.1")
        self._remote_port = self._spin(1, 65535, mapping.remote_port if mapping else 5432)
        self._auto_reconnect = QCheckBox()
        self._auto_reconnect.setChecked(mapping.auto_reconnect if mapping else True)
        self._enabled = QCheckBox()
        self._enabled.setChecked(mapping.enabled if mapping else True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_form)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        form.addRow("SSH Host", self._ssh_host)
        form.addRow("SSH Port", self._ssh_port)
        form.addRow("SSH Username", self._ssh_username)
        form.addRow("SSH Password", self._password)
        form.addRow("Identity File", identity_row)
        form.addRow("Local Host", self._local_host)
        form.addRow("Local Port", self._local_port)
        form.addRow("Remote Host", self._remote_host)
        form.addRow("Remote Port", self._remote_port)
        form.addRow("Auto Reconnect", self._auto_reconnect)
        form.addRow("Enabled", self._enabled)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def to_input(self) -> PortMappingInput:
        return PortMappingInput(
            name=self._name.text().strip(),
            description=self._description.toPlainText().strip(),
            ssh_host=self._ssh_host.text().strip(),
            ssh_username=self._ssh_username.text().strip(),
            ssh_port=self._ssh_port.value(),
            password=self._password.text() or None,
            identity_file=self._identity_file.text().strip() or None,
            local_host=self._local_host.text().strip(),
            local_port=self._local_port.value(),
            remote_host=self._remote_host.text().strip(),
            remote_port=self._remote_port.value(),
            auto_reconnect=self._auto_reconnect.isChecked(),
            enabled=self._enabled.isChecked(),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self._name.text().strip():
            errors.append("Mapping name is required.")
        if not self._ssh_host.text().strip():
            errors.append("SSH host is required.")
        if not self._ssh_username.text().strip():
            errors.append("SSH username is required.")
        if not self._local_host.text().strip():
            errors.append("Local host is required.")
        if not self._remote_host.text().strip():
            errors.append("Remote host is required.")
        for label, field in (
            ("SSH host", self._ssh_host),
            ("SSH username", self._ssh_username),
            ("Local host", self._local_host),
            ("Remote host", self._remote_host),
        ):
            if any(char in field.text() for char in "\r\n\x00"):
                errors.append(f"{label} contains an invalid control character.")
        if self._identity_file.text().strip() and not Path(self._identity_file.text().strip()).expanduser().is_file():
            errors.append("The selected SSH identity file does not exist.")
        return errors

    def _accept_form(self) -> None:
        errors = self.validation_errors()
        if errors:
            QMessageBox.warning(self, "Invalid SSH Mapping", "\n".join(errors))
            return
        self.accept()

    def _browse_identity(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Identity File",
            str(Path.home() / ".ssh"),
            "SSH Keys (*)",
        )
        if path:
            self._identity_file.setText(path)

    def _spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin
