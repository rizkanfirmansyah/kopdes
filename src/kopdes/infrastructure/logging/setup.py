from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_level: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "kopdes.log"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.insert(0, logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
