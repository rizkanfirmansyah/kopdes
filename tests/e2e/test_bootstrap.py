from pathlib import Path

from kopdes.bootstrap import build_application


def test_build_application_creates_window(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    secret_key_path = tmp_path / "secret.key"
    config_path.write_text(
        "\n".join(
            [
                "app_name: KOPDES",
                f"database_url: sqlite:///{data_dir / 'kopdes.db'}",
                "log_level: INFO",
                f"secret_key_path: {secret_key_path}",
                f"data_dir: {data_dir}",
                "refresh_interval_ms: 10000",
            ]
        ),
        encoding="utf-8",
    )
    context = build_application(config_path)
    assert context.window.windowTitle() == "KOPDES"


def test_build_application_falls_back_when_paths_are_not_writable(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    data_dir = tmp_path / "blocked-data"
    secret_key_path = tmp_path / "blocked-secret" / "secret.key"
    config_path.write_text(
        "\n".join(
            [
                "app_name: KOPDES",
                f"database_url: sqlite:///{data_dir / 'kopdes.db'}",
                "log_level: INFO",
                f"secret_key_path: {secret_key_path}",
                f"data_dir: {data_dir}",
                "refresh_interval_ms: 10000",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr('kopdes.bootstrap._settings_are_writable', lambda settings: False)

    context = build_application(config_path)

    assert context.window.windowTitle() == "KOPDES"
