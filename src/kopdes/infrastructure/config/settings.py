from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class AppSettings:
    app_name: str
    database_url: str
    log_level: str
    secret_key_path: Path
    data_dir: Path
    refresh_interval_ms: int = 1000

    @classmethod
    def default(cls) -> "AppSettings":
        home = Path.home()
        data_dir = home / ".local" / "share" / "kopdes"
        return cls(
            app_name="KOPDES",
            database_url=f"sqlite:///{data_dir / 'kopdes.db'}",
            log_level="INFO",
            secret_key_path=home / ".config" / "kopdes" / "secret.key",
            data_dir=data_dir,
            refresh_interval_ms=1000,
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "AppSettings":
        if not path.exists():
            return cls.default()
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        default = cls.default()
        return cls(
            app_name=payload.get("app_name", default.app_name),
            database_url=payload.get("database_url", default.database_url),
            log_level=payload.get("log_level", default.log_level),
            secret_key_path=Path(payload.get("secret_key_path", default.secret_key_path)),
            data_dir=Path(payload.get("data_dir", default.data_dir)),
            refresh_interval_ms=int(
                payload.get("refresh_interval_ms", default.refresh_interval_ms)
            ),
        )
