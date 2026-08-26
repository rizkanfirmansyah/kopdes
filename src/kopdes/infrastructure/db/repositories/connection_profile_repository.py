from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from kopdes.application.ports.repositories import ConnectionProfileRepository
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.db.models.connection_profile import ConnectionProfileModel
from kopdes.infrastructure.db.models.tag import TagModel
from kopdes.shared.enums import ProtocolType


class SqlAlchemyConnectionProfileRepository(ConnectionProfileRepository):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def save(self, profile: ConnectionProfile) -> ConnectionProfile:
        with self._session_factory() as session:
            existing = session.get(ConnectionProfileModel, profile.id)
            model = existing or ConnectionProfileModel(id=profile.id)
            model.name = profile.name
            model.description = profile.description
            model.protocol = profile.protocol.value
            model.server_address = profile.server_address
            model.port = profile.port
            model.username = profile.username
            model.encrypted_password = profile.encrypted_password
            model.route_metric = profile.route_metric
            model.dns_servers = ",".join(profile.dns_servers)
            model.mtu = profile.mtu
            model.keepalive = profile.keepalive
            model.auto_reconnect = profile.auto_reconnect
            model.allow_multiple = profile.allow_multiple
            model.config_payload = json.dumps(profile.config_payload)
            model.tags = [self._get_or_create_tag(session, tag) for tag in profile.tags]
            session.add(model)
            session.commit()
            session.refresh(model)
            return self._to_entity(model)

    def list_all(self) -> list[ConnectionProfile]:
        with self._session_factory() as session:
            models = session.query(ConnectionProfileModel).order_by(ConnectionProfileModel.name).all()
            return [self._to_entity(item) for item in models]

    def get_by_name(self, name: str) -> ConnectionProfile | None:
        with self._session_factory() as session:
            model = (
                session.query(ConnectionProfileModel)
                .filter(ConnectionProfileModel.name == name)
                .one_or_none()
            )
            return self._to_entity(model) if model else None

    def get_by_id(self, profile_id: str) -> ConnectionProfile | None:
        with self._session_factory() as session:
            model = session.get(ConnectionProfileModel, profile_id)
            return self._to_entity(model) if model else None

    def delete(self, profile_id: str) -> None:
        with self._session_factory() as session:
            model = session.get(ConnectionProfileModel, profile_id)
            if model is None:
                return
            session.delete(model)
            session.commit()

    def _get_or_create_tag(self, session, name: str) -> TagModel:
        tag = session.query(TagModel).filter(TagModel.name == name).one_or_none()
        if tag:
            return tag
        tag = TagModel(id=str(uuid4()), name=name)
        session.add(tag)
        session.flush()
        return tag

    def _to_entity(self, model: ConnectionProfileModel) -> ConnectionProfile:
        return ConnectionProfile(
            id=model.id,
            name=model.name,
            description=model.description,
            server_address=model.server_address,
            protocol=ProtocolType(model.protocol),
            port=model.port,
            username=model.username,
            encrypted_password=model.encrypted_password,
            route_metric=model.route_metric,
            dns_servers=[item for item in model.dns_servers.split(",") if item],
            mtu=model.mtu,
            keepalive=model.keepalive,
            auto_reconnect=model.auto_reconnect,
            allow_multiple=model.allow_multiple,
            tags=[tag.name for tag in model.tags],
            config_payload=json.loads(model.config_payload or "{}"),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
