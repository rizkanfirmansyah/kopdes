import sys

import pytest
from PySide6.QtWidgets import QApplication

from kopdes.shared.enums import ProtocolType
from kopdes.ui.dialogs.port_mapping_dialog import PortMappingDialog
from kopdes.ui.dialogs.profile_dialog import ProfileDialog


def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.mark.parametrize("protocol", tuple(ProtocolType))
def test_profile_dialog_accepts_qt_protocol_data(protocol: ProtocolType) -> None:
    qt_app()
    dialog = ProfileDialog()
    dialog._name.setText(f"{protocol.value}-manual")
    dialog._server.setText("vpn.example.net")
    dialog._username.setText("operator")
    dialog._password.setText("secret")
    dialog._protocol.setCurrentText(protocol.value.upper())

    assert dialog.validation_errors() == []
    data = dialog.to_input()
    assert isinstance(data.protocol, ProtocolType)
    assert data.protocol == protocol


def test_port_mapping_dialog_produces_valid_input() -> None:
    qt_app()
    dialog = PortMappingDialog()
    dialog._name.setText("PostgreSQL local")
    dialog._ssh_host.setText("192.168.0.10")
    dialog._ssh_username.setText("boss")
    dialog._password.setText("ssh-secret")
    dialog._remote_host.setText("localhost")

    assert dialog.validation_errors() == []
    data = dialog.to_input()
    assert data.local_port == 5433
    assert data.remote_port == 5432
    assert data.password == "ssh-secret"
