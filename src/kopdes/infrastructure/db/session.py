from __future__ import annotations

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker


def create_engine(database_url: str):
    return sa_create_engine(database_url, future=True)


def create_session_factory(database_url: str) -> sessionmaker:
    engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
