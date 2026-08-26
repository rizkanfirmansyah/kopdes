from __future__ import annotations

from kopdes.infrastructure.db.base import Base
from kopdes.infrastructure.db.session import create_engine


def bootstrap_database(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
