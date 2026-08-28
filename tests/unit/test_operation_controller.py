import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from kopdes.ui.operation_controller import OperationController


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_operation_controller_rejects_duplicate_and_delivers_result(qt_app) -> None:
    del qt_app
    controller = OperationController(max_threads=2)
    loop = QEventLoop()
    results: list[object] = []
    errors: list[Exception] = []
    controller.operation_finished.connect(lambda key: loop.quit() if key == "sample" else None)

    assert controller.submit(
        "sample",
        lambda: (time.sleep(0.05), "ok")[1],
        results.append,
        errors.append,
    )
    assert not controller.submit("sample", lambda: "duplicate")
    QTimer.singleShot(2000, loop.quit)
    loop.exec()

    assert results == ["ok"]
    assert errors == []
    controller.shutdown()



def test_cancel_pending_releases_queued_keys_and_suppresses_callbacks(qt_app) -> None:
    del qt_app
    controller = OperationController(max_threads=2)
    results: list[object] = []

    assert controller.submit("first", lambda: (time.sleep(0.25), "first")[1], results.append)
    assert controller.submit("second", lambda: (time.sleep(0.25), "second")[1], results.append)
    assert controller.submit("queued", lambda: "queued", results.append)
    controller.cancel_pending()

    assert not controller.is_running("queued")
    loop = QEventLoop()
    QTimer.singleShot(1000, loop.quit)
    loop.exec()

    assert results == []
    assert not controller.is_running("first")
    assert not controller.is_running("second")
    controller.shutdown()
