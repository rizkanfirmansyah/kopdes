from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.infrastructure.db.base import Base
from kopdes.infrastructure.db.migrations import (
    MIGRATIONS,
    Migration,
    get_schema_version,
    migrate_database,
)
from kopdes.infrastructure.db.session import create_engine


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def _version(path: Path) -> int:
    engine = create_engine(_url(path))
    try:
        with engine.connect() as connection:
            return get_schema_version(connection)
    finally:
        engine.dispose()


def test_empty_database_is_migrated_and_versioned(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"

    bootstrap_database(_url(db_path))

    assert _version(db_path) == 1
    engine = create_engine(_url(db_path))
    try:
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)
    finally:
        engine.dispose()


def test_old_database_preserves_profiles_and_creates_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA user_version = 0")
            connection.execute(
                text(
                    "INSERT INTO connection_profiles "
                    "(id, name, description, protocol, server_address, route_metric, dns_servers, auto_reconnect, allow_multiple, config_payload, created_at, updated_at) "
                    "VALUES (:id, :name, :description, :protocol, :server, 100, '', 1, 0, :payload, :created, :created)"
                ),
                {
                    "id": "profile-old",
                    "name": "Old profile",
                    "description": "preserve",
                    "protocol": "openvpn",
                    "server": "vpn.example",
                    "payload": "{}",
                    "created": "2026-01-01T00:00:00",
                },
            )
    finally:
        engine.dispose()

    bootstrap_database(_url(db_path))

    assert _version(db_path) == 1
    backup = tmp_path / "old.db.pre-migration-v1.bak"
    assert backup.is_file()
    assert (backup.stat().st_mode & 0o777) == 0o600
    engine = create_engine(_url(db_path))
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT name, server_address FROM connection_profiles WHERE id = 'profile-old'")
            ).one()
            assert tuple(row) == ("Old profile", "vpn.example")
    finally:
        engine.dispose()


def test_existing_mapping_and_malformed_payload_survive_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO connection_profiles "
                    "(id, name, description, protocol, server_address, route_metric, dns_servers, auto_reconnect, allow_multiple, config_payload, created_at, updated_at) "
                    "VALUES ('bad', 'Bad payload', '', 'openvpn', 'vpn.example', 100, '', 1, 0, '{not-json}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO port_mappings "
                    "(id, name, description, ssh_host, ssh_port, ssh_username, local_host, local_port, remote_host, remote_port, auto_reconnect, enabled, created_at, updated_at) "
                    "VALUES ('map-1', 'DB', '', '192.0.2.10', 22, 'boss', '127.0.0.1', 5433, '127.0.0.1', 5432, 1, 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
                )
            )
    finally:
        engine.dispose()

    bootstrap_database(_url(db_path))

    engine = create_engine(_url(db_path))
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM port_mappings")).scalar_one() == 1
            assert connection.execute(text("SELECT config_payload FROM connection_profiles WHERE id = 'bad'")).scalar_one() == "{not-json}"
    finally:
        engine.dispose()


def test_failed_migration_rolls_back_schema_and_version(tmp_path: Path) -> None:
    db_path = tmp_path / "failure.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))

    def apply_two(connection) -> None:
        connection.exec_driver_sql("CREATE TABLE migration_two_marker (id INTEGER PRIMARY KEY)")
        raise RuntimeError("synthetic migration failure")

    failing = Migration(version=2, apply=apply_two, validate=lambda _connection: None)

    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        migrate_database(engine, migrations=(*MIGRATIONS, failing))

    try:
        with engine.connect() as connection:
            assert get_schema_version(connection) == 1
            assert "migration_two_marker" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()
    assert (tmp_path / "failure.db.pre-migration-v2.bak").is_file()


def test_sequential_migrations_apply_and_validate_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / "sequence.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))
    calls: list[int] = []

    def apply_two(connection) -> None:
        calls.append(2)
        connection.exec_driver_sql("CREATE TABLE migration_two (id INTEGER PRIMARY KEY)")

    def validate_two(connection) -> None:
        assert "migration_two" in inspect(connection).get_table_names()

    def apply_three(connection) -> None:
        calls.append(3)
        connection.exec_driver_sql("CREATE TABLE migration_three (id INTEGER PRIMARY KEY)")

    def validate_three(connection) -> None:
        assert "migration_three" in inspect(connection).get_table_names()

    migrations = (
        *MIGRATIONS,
        Migration(2, apply_two, validate_two),
        Migration(3, apply_three, validate_three),
    )
    try:
        assert migrate_database(engine, migrations=migrations) == 3
        with engine.connect() as connection:
            assert get_schema_version(connection) == 3
            assert calls == [2, 3]
    finally:
        engine.dispose()


def test_migration_rejects_future_schema_without_touching_database(tmp_path: Path) -> None:
    db_path = tmp_path / "future.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA user_version = 99")
        with pytest.raises(RuntimeError, match="newer"):
            migrate_database(engine)
    finally:
        engine.dispose()


def test_migration_definitions_require_unique_sequential_versions(tmp_path: Path) -> None:
    db_path = tmp_path / "definitions.db"
    bootstrap_database(_url(db_path))
    engine = create_engine(_url(db_path))
    duplicate = Migration(2, lambda _connection: None, lambda _connection: None)
    try:
        with pytest.raises(RuntimeError, match="unique"):
            migrate_database(engine, migrations=(*MIGRATIONS, duplicate, duplicate))
        with pytest.raises(RuntimeError, match="Missing migration version"):
            migrate_database(engine, migrations=(*MIGRATIONS, Migration(3, lambda _connection: None, lambda _connection: None)))
    finally:
        engine.dispose()
