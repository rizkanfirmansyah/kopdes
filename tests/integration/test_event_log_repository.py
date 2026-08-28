from pathlib import Path
from uuid import uuid4

from kopdes.domain.entities.event_log import EventLog
from kopdes.infrastructure.db.repositories.event_log_repository import (
    SqlAlchemyEventLogRepository,
)
from kopdes.infrastructure.db.session import create_session_factory
from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.shared.enums import EventLevel


def test_event_log_repository_prunes_old_events(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'events.db'}"
    bootstrap_database(database_url)
    repository = SqlAlchemyEventLogRepository(create_session_factory(database_url))
    repository.MAX_STORED_EVENTS = 3

    for index in range(5):
        repository.append(
            EventLog(
                id=str(uuid4()),
                profile_id=None,
                level=EventLevel.INFO,
                event_type="test",
                message=f"event-{index}",
            )
        )

    events = repository.list_recent(100)

    assert len(events) == 3
    assert {event.message for event in events} == {"event-2", "event-3", "event-4"}
