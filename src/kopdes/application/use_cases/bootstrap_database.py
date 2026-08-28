from __future__ import annotations

from kopdes.infrastructure.db.base import Base
from kopdes.infrastructure.db.session import create_engine

# Import every model here so database creation does not depend on unrelated
# application import order (for example, importing only one repository).
from kopdes.infrastructure.db.models import connection_profile as _connection_profile
from kopdes.infrastructure.db.models import connection_session as _connection_session
from kopdes.infrastructure.db.models import event_log as _event_log
from kopdes.infrastructure.db.models import health_check as _health_check
from kopdes.infrastructure.db.models import port_mapping as _port_mapping
from kopdes.infrastructure.db.models import route_policy as _route_policy
from kopdes.infrastructure.db.models import tag as _tag


def bootstrap_database(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
