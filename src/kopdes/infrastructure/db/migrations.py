from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, inspect

from kopdes.infrastructure.db.base import Base


LOGGER = logging.getLogger(__name__)
CURRENT_SCHEMA_VERSION = 1
_EXPECTED_TABLES = frozenset(
    {
        "connection_profiles",
        "connection_sessions",
        "event_logs",
        "health_checks",
        "port_mappings",
        "profile_tags",
        "route_policies",
        "tags",
    }
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    apply: Callable[[Connection], None]
    validate: Callable[[Connection], None]


def _load_models() -> None:
    # Keep model registration deterministic when this module is used directly.
    from kopdes.infrastructure.db.models import connection_profile as _connection_profile
    from kopdes.infrastructure.db.models import connection_session as _connection_session
    from kopdes.infrastructure.db.models import event_log as _event_log
    from kopdes.infrastructure.db.models import health_check as _health_check
    from kopdes.infrastructure.db.models import port_mapping as _port_mapping
    from kopdes.infrastructure.db.models import route_policy as _route_policy
    from kopdes.infrastructure.db.models import tag as _tag

    del (
        _connection_profile,
        _connection_session,
        _event_log,
        _health_check,
        _port_mapping,
        _route_policy,
        _tag,
    )


def get_schema_version(connection: Connection) -> int:
    value = connection.exec_driver_sql("PRAGMA user_version").scalar()
    try:
        version = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("SQLite schema version is invalid.") from exc
    if version < 0:
        raise RuntimeError("SQLite schema version cannot be negative.")
    return version


def _set_schema_version(connection: Connection, version: int) -> None:
    if version < 0:
        raise ValueError("Schema version cannot be negative.")
    connection.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def _validate_schema(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    missing = sorted(_EXPECTED_TABLES - tables)
    if missing:
        raise RuntimeError(f"Schema validation failed; missing tables: {', '.join(missing)}")


def _migration_001(connection: Connection) -> None:
    Base.metadata.create_all(connection)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, apply=_migration_001, validate=_validate_schema),
)


def _validate_migrations(migrations: Sequence[Migration]) -> list[Migration]:
    ordered = sorted(migrations, key=lambda migration: migration.version)
    versions = [migration.version for migration in ordered]
    if any(version <= 0 for version in versions):
        raise RuntimeError("Migration versions must be positive.")
    if len(versions) != len(set(versions)):
        raise RuntimeError("Migration versions must be unique.")
    return ordered


def _sqlite_path(engine: Engine) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    path = Path(database).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def backup_sqlite_database(engine: Engine, target_version: int) -> Path | None:
    path = _sqlite_path(engine)
    if path is None or not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.pre-migration-v{target_version}.bak")
    temporary_path: Path | None = None
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{backup_path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        source = sqlite3.connect(str(path))
        destination = sqlite3.connect(str(temporary_path))
        try:
            source.backup(destination)
            destination.commit()
        finally:
            source.close()
            destination.close()
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, backup_path)
        os.chmod(backup_path, 0o600)
        return backup_path
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(f"Could not create SQLite migration backup: {path}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove temporary migration backup %s", temporary_path)


def migrate_database(
    engine: Engine,
    *,
    database_url: str | None = None,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> int:
    del database_url
    _load_models()
    ordered = _validate_migrations(migrations)
    if engine.dialect.name != "sqlite":
        Base.metadata.create_all(engine)
        return CURRENT_SCHEMA_VERSION

    with engine.connect() as connection:
        current = get_schema_version(connection)

    latest = ordered[-1].version if ordered else 0
    if current > latest:
        raise RuntimeError(
            f"Database schema version {current} is newer than this KOPDES build ({latest})."
        )
    pending = [migration for migration in ordered if migration.version > current]
    expected_version = current + 1
    for migration in pending:
        if migration.version != expected_version:
            raise RuntimeError(
                f"Missing migration version {expected_version} before {migration.version}."
            )
        expected_version += 1

    if pending:
        backup = backup_sqlite_database(engine, pending[0].version)
        if backup is not None:
            LOGGER.info("SQLite migration backup created at %s", backup)

    if not pending:
        with engine.connect() as connection:
            _validate_schema(connection)
        return current

    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            for migration in pending:
                migration.apply(connection)
                migration.validate(connection)
                _set_schema_version(connection, migration.version)
            connection.commit()
        except Exception:
            connection.rollback()
            LOGGER.exception("SQLite migration failed; transaction rolled back")
            raise
    return pending[-1].version
