from __future__ import annotations

import logging

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker


LOGGER = logging.getLogger(__name__)


def create_engine(database_url: str):
    options = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 10}
    engine = sa_create_engine(database_url, **options)
    if database_url.startswith("sqlite:"):
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine) -> None:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in (
                "PRAGMA busy_timeout=10000",
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
            ):
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    # SQLite variants may reject WAL or synchronous settings;
                    # the connection remains usable with its default mode.
                    LOGGER.warning("SQLite pragma failed (%s): %s", statement, exc)
        finally:
            cursor.close()


def create_session_factory(database_url: str) -> sessionmaker:
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
