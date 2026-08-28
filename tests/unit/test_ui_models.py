import pytest
from PySide6.QtWidgets import QApplication

from kopdes.application.dtos.runtime_state import ConnectionRow
from kopdes.shared.enums import ConnectionStatus
from kopdes.ui.models.connection_table_model import ConnectionTableModel
from kopdes.ui.pages import ConnectionFilterProxyModel


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _row(profile_id: str, status: ConnectionStatus, name: str = "VPN") -> ConnectionRow:
    return ConnectionRow(
        profile_id=profile_id,
        status=status,
        name=name,
        protocol="openvpn",
        server="vpn.example.test",
    )


def test_connection_model_status_override_is_transient() -> None:
    model = ConnectionTableModel()
    model.set_rows([_row("one", ConnectionStatus.INACTIVE)])

    model.set_status_override("one", ConnectionStatus.CONNECTING)
    assert model.data(model.index(0, 0)).startswith("CONNECTING")

    model.clear_status_override("one")
    assert model.data(model.index(0, 0)) == "DISCONNECTED"


def test_connection_filter_combines_state_and_text(qt_app) -> None:
    del qt_app
    model = ConnectionTableModel()
    model.set_rows(
        [
            _row("one", ConnectionStatus.ACTIVE, "Primary"),
            _row("two", ConnectionStatus.FAILED, "Backup"),
        ]
    )
    proxy = ConnectionFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_status("failed")
    proxy.set_query("Backup")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1)).startswith("Backup")

    proxy.set_query("Primary")
    assert proxy.rowCount() == 0

    proxy.set_status("connected")
    proxy.set_query("")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1)).startswith("Primary")
