from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_level: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "kopdes.log"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.insert(
            0,
            RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
        )
    except OSError as exc:
        # Keep console logging available, but make an unwritable data path visible.
        logging.getLogger(__name__).warning(
            "File logging is unavailable at %s: %s",
            log_path,
            exc,
        )
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
