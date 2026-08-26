from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from kopdes.application.ports.repositories import EventLogRepository
from kopdes.domain.entities.event_log import EventLog
from kopdes.infrastructure.db.models.event_log import EventLogModel
from kopdes.shared.enums import EventLevel


class SqlAlchemyEventLogRepository(EventLogRepository):
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
            session.commit()
            session.refresh(model)
            return self._to_entity(model)

    def list_recent(self, limit: int = 200) -> list[EventLog]:
        with self._session_factory() as session:
            rows = (
                session.query(EventLogModel)
                .order_by(EventLogModel.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._to_entity(row) for row in rows]

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
