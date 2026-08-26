from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from kopdes.application.dtos.connection_profile_dto import ConnectionProfileInput
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.shared.enums import ProtocolType


class ProfileDialog(QDialog):
    def __init__(self, profile: ConnectionProfile | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Connection Profile")
        self.resize(520, 620)
        self._profile = profile

        self._name = QLineEdit(profile.name if profile else "")
        self._description = QPlainTextEdit(profile.description if profile else "")
        self._server = QLineEdit(profile.server_address if profile else "")
        self._port = QSpinBox()
        self._port.setRange(0, 65535)
        self._port.setValue(profile.port or 0 if profile else 0)
        self._protocol = QComboBox()
        for protocol in ProtocolType:
            self._protocol.addItem(protocol.value, protocol)
        if profile:
            self._protocol.setCurrentText(profile.protocol.value)
        self._username = QLineEdit(profile.username or "" if profile else "")
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._metric = QSpinBox()
        self._metric.setRange(1, 9999)
        self._metric.setValue(profile.route_metric if profile else 100)
        self._dns = QLineEdit(",".join(profile.dns_servers) if profile else "")
        self._mtu = QSpinBox()
        self._mtu.setRange(0, 9200)
        self._mtu.setValue(profile.mtu or 0 if profile else 0)
        self._keepalive = QSpinBox()
        self._keepalive.setRange(0, 3600)
        self._keepalive.setValue(profile.keepalive or 0 if profile else 0)
        self._tags = QLineEdit(",".join(profile.tags) if profile else "")
        self._auto_reconnect = QCheckBox()
        self._auto_reconnect.setChecked(profile.auto_reconnect if profile else True)
        self._allow_multiple = QCheckBox()
        self._allow_multiple.setChecked(profile.allow_multiple if profile else False)
        self._interface_name = QLineEdit(str(profile.config_payload.get("interface_name", "")) if profile else "")
        self._peer_name = QLineEdit(str(profile.config_payload.get("peer_name", "")) if profile else "")
        self._ipsec_psk = QLineEdit()
        self._ipsec_psk.setEchoMode(QLineEdit.EchoMode.Password)
        self._ipsec_psk.setPlaceholderText("Leave blank to keep existing PSK")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        form.addRow("Protocol", self._protocol)
        form.addRow("Server", self._server)
        form.addRow("Port", self._port)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)
        form.addRow("Route Metric", self._metric)
        form.addRow("DNS", self._dns)
        form.addRow("MTU", self._mtu)
        form.addRow("Keepalive", self._keepalive)
        form.addRow("Interface", self._interface_name)
        form.addRow("PPP Peer", self._peer_name)
        form.addRow("IPSec PSK", self._ipsec_psk)
        form.addRow("Tags", self._tags)
        form.addRow("Auto Reconnect", self._auto_reconnect)
        form.addRow("Allow Multiple", self._allow_multiple)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def to_input(self) -> ConnectionProfileInput:
        protocol = self._protocol.currentData()
        config_payload = {}
        if self._interface_name.text().strip():
            config_payload["interface_name"] = self._interface_name.text().strip()
        if self._peer_name.text().strip():
            config_payload["peer_name"] = self._peer_name.text().strip()
        if self._ipsec_psk.text().strip():
            config_payload["ipsec_psk"] = self._ipsec_psk.text().strip()
        if self._profile:
            config_payload = {**self._profile.config_payload, **config_payload}
        return ConnectionProfileInput(
            name=self._name.text().strip(),
            description=self._description.toPlainText().strip(),
            server_address=self._server.text().strip(),
            protocol=protocol,
            port=self._port.value() or None,
            username=self._username.text().strip() or None,
            password=self._password.text() or None,
            route_metric=self._metric.value(),
            dns_servers=[item.strip() for item in self._dns.text().split(",") if item.strip()],
            mtu=self._mtu.value() or None,
            keepalive=self._keepalive.value() or None,
            auto_reconnect=self._auto_reconnect.isChecked(),
            allow_multiple=self._allow_multiple.isChecked(),
            tags=[item.strip() for item in self._tags.text().split(",") if item.strip()],
            config_payload=config_payload,
        )
