from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from kopdes.bootstrap import build_application


LOGGER = logging.getLogger(__name__)


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        context = build_application(config_path)
    except Exception as exc:
        LOGGER.exception("KOPDES bootstrap failed")
        app = QApplication.instance() or QApplication(sys.argv)
        message = str(exc).strip() or exc.__class__.__name__
        QMessageBox.critical(None, "KOPDES Startup Error", message)
        return 1

    context.app.aboutToQuit.connect(context.window.shutdown)
    context.window.show()
    try:
        return context.app.exec()
    except Exception:
        LOGGER.exception("KOPDES event loop failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
