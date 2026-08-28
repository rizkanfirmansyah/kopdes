from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from kopdes.bootstrap import build_application


LOGGER = logging.getLogger(__name__)


def _install_exception_logging() -> None:
    previous_hook = sys.excepthook
    logging.basicConfig(level=logging.ERROR)

    def handle_exception(exc_type, exc_value, traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, traceback)
            return
        LOGGER.critical(
            "Unhandled KOPDES exception",
            exc_info=(exc_type, exc_value, traceback),
        )

    sys.excepthook = handle_exception


def main() -> int:
    _install_exception_logging()
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        context = build_application(config_path)
    except Exception as exc:
        LOGGER.exception("KOPDES bootstrap failed")
        app = QApplication.instance() or QApplication(sys.argv)
        message = str(exc).strip() or exc.__class__.__name__
        QMessageBox.critical(None, "KOPDES Startup Error", message)
        return 1

    context.window.show()
    try:
        return context.app.exec()
    except Exception:
        LOGGER.exception("KOPDES event loop failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
