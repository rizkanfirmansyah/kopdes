from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from kopdes.application.ports.repositories import EventLogRepository
from kopdes.domain.entities.event_log import EventLog
from kopdes.infrastructure.db.models.event_log import EventLogModel
from kopdes.shared.enums import EventLevel


LOGGER = logging.getLogger(__name__)


class SqlAlchemyEventLogRepository(EventLogRepository):
    MAX_STORED_EVENTS = 10_000

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def append(self, event: EventLog) -> EventLog:
        with self._session_factory() as session:
            model = EventLogModel(
                id=event.id,
                profile_id=event.profile_id,
                level=event.level.value,
                event_type=event.event_type,
                message=event.message,
                details=event.details,
            )
            session.add(model)
            session.flush()
            overflow = session.query(EventLogModel).count() - self.MAX_STORED_EVENTS
            if overflow > 0:
                old_rows = (
                    session.query(EventLogModel)
                    .filter(EventLogModel.id != model.id)
                    .order_by(EventLogModel.created_at.asc(), EventLogModel.id.asc())
                    .limit(overflow)
                    .all()
                )
                for old_row in old_rows:
                    session.delete(old_row)
            session.commit()
            session.refresh(model)
            return self._to_entity(model)

    def list_recent(self, limit: int = 200) -> list[EventLog]:
        try:
            requested = max(1, min(int(limit), self.MAX_STORED_EVENTS))
        except (TypeError, ValueError):
            requested = 200
        with self._session_factory() as session:
            rows = (
                session.query(EventLogModel)
                .order_by(EventLogModel.created_at.desc())
                .limit(requested)
                .all()
            )
            events: list[EventLog] = []
            for row in rows:
                try:
                    events.append(self._to_entity(row))
                except (TypeError, ValueError) as exc:
                    LOGGER.error("Skipping malformed event log id=%s: %s", row.id, exc)
            return events

    def _to_entity(self, model: EventLogModel) -> EventLog:
        return EventLog(
            id=model.id,
            profile_id=model.profile_id,
            level=EventLevel(model.level),
            event_type=model.event_type,
            message=model.message,
            details=model.details,
            created_at=model.created_at,
        )
