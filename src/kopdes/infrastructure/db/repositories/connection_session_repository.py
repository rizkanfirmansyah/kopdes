from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from kopdes.application.ports.repositories import ConnectionSessionRepository
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.infrastructure.db.models.connection_session import ConnectionSessionModel
from kopdes.shared.enums import ConnectionStatus


LOGGER = logging.getLogger(__name__)


class SqlAlchemyConnectionSessionRepository(ConnectionSessionRepository):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def save(self, session_entity: ConnectionSession) -> ConnectionSession:
        with self._session_factory() as session:
            model = session.get(ConnectionSessionModel, session_entity.id)
            if model is None:
                model = ConnectionSessionModel(id=session_entity.id)
            model.profile_id = session_entity.profile_id
            model.status = session_entity.status.value
            model.started_at = session_entity.started_at
            model.ended_at = session_entity.ended_at
            model.latency_ms = session_entity.latency_ms
            model.packet_loss = session_entity.packet_loss
            model.jitter_ms = session_entity.jitter_ms
            model.bytes_in = session_entity.bytes_in
            model.bytes_out = session_entity.bytes_out
            model.reconnect_count = session_entity.reconnect_count
            model.last_error = session_entity.last_error
            model.local_ip = session_entity.local_ip
            model.remote_ip = session_entity.remote_ip
            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_entity(model)

    def list_latest(self) -> list[ConnectionSession]:
        with self._session_factory() as session:
            rows = (
                session.query(ConnectionSessionModel)
                .order_by(
                    ConnectionSessionModel.started_at.desc().nullslast(),
                    ConnectionSessionModel.id.desc(),
                )
                .all()
            )
            entities: list[ConnectionSession] = []
            for row in rows:
                try:
                    entities.append(self._to_entity(row))
                except (TypeError, ValueError) as exc:
                    LOGGER.error("Skipping malformed connection session id=%s: %s", row.id, exc)
            return entities

    def _to_entity(self, model: ConnectionSessionModel) -> ConnectionSession:
        return ConnectionSession(
            id=model.id,
            profile_id=model.profile_id,
            status=ConnectionStatus(model.status),
            started_at=model.started_at,
            ended_at=model.ended_at,
            latency_ms=model.latency_ms,
            packet_loss=model.packet_loss,
            jitter_ms=model.jitter_ms,
            bytes_in=model.bytes_in,
            bytes_out=model.bytes_out,
            reconnect_count=model.reconnect_count,
            last_error=model.last_error,
            local_ip=model.local_ip,
            remote_ip=model.remote_ip,
        )
