from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from kopdes.application.ports.repositories import PortMappingRepository
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.db.models.port_mapping import PortMappingModel


LOGGER = logging.getLogger(__name__)


class SqlAlchemyPortMappingRepository(PortMappingRepository):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def save(self, mapping: PortMapping) -> PortMapping:
        with self._session_factory() as session:
            model = session.get(PortMappingModel, mapping.id) or PortMappingModel(id=mapping.id)
            model.name = mapping.name
            model.description = mapping.description
            model.ssh_host = mapping.ssh_host
            model.ssh_port = mapping.ssh_port
            model.ssh_username = mapping.ssh_username
            model.local_host = mapping.local_host
            model.local_port = mapping.local_port
            model.remote_host = mapping.remote_host
            model.remote_port = mapping.remote_port
            model.identity_file = mapping.identity_file
            model.encrypted_password = mapping.encrypted_password
            model.auto_reconnect = mapping.auto_reconnect
            model.enabled = mapping.enabled
            model.last_error = mapping.last_error
            model.last_started_at = mapping.last_started_at
            model.last_stopped_at = mapping.last_stopped_at
            if mapping.created_at is not None:
                model.created_at = mapping.created_at
            if mapping.updated_at is not None:
                model.updated_at = mapping.updated_at
            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_entity(model)

    def list_all(self) -> list[PortMapping]:
        with self._session_factory() as session:
            models = session.query(PortMappingModel).order_by(PortMappingModel.name).all()
            entities: list[PortMapping] = []
            for model in models:
                try:
                    entities.append(self._to_entity(model))
                except (TypeError, ValueError) as exc:
                    LOGGER.error("Skipping malformed SSH mapping id=%s: %s", model.id, exc)
            return entities

    def get_by_id(self, mapping_id: str) -> PortMapping | None:
        with self._session_factory() as session:
            model = session.get(PortMappingModel, mapping_id)
            if model is None:
                return None
            try:
                return self._to_entity(model)
            except (TypeError, ValueError) as exc:
                LOGGER.error("Malformed SSH mapping id=%s: %s", model.id, exc)
                return None

    def get_by_name(self, name: str) -> PortMapping | None:
        with self._session_factory() as session:
            model = session.query(PortMappingModel).filter(PortMappingModel.name == name).one_or_none()
            if model is None:
                return None
            try:
                return self._to_entity(model)
            except (TypeError, ValueError) as exc:
                LOGGER.error("Malformed SSH mapping id=%s: %s", model.id, exc)
                return None

    def delete(self, mapping_id: str) -> None:
        with self._session_factory() as session:
            model = session.get(PortMappingModel, mapping_id)
            if model is None:
                return
            session.delete(model)
            session.commit()

    def _to_entity(self, model: PortMappingModel) -> PortMapping:
        return PortMapping(
            id=model.id,
            name=model.name,
            description=model.description,
            ssh_host=model.ssh_host,
            ssh_port=model.ssh_port,
            ssh_username=model.ssh_username,
            local_host=model.local_host,
            local_port=model.local_port,
            remote_host=model.remote_host,
            remote_port=model.remote_port,
            identity_file=model.identity_file,
            encrypted_password=model.encrypted_password,
            auto_reconnect=model.auto_reconnect,
            enabled=model.enabled,
            last_error=model.last_error,
            last_started_at=model.last_started_at,
            last_stopped_at=model.last_stopped_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
