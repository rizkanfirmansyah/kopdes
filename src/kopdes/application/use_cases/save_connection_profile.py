from __future__ import annotations

from uuid import uuid4

from kopdes.application.dtos.connection_profile_dto import ConnectionProfileInput
from kopdes.application.ports.repositories import ConnectionProfileRepository
from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.infrastructure.security.crypto import SecretManager


class SaveConnectionProfileUseCase:
    def __init__(
        self,
        repository: ConnectionProfileRepository,
        secret_manager: SecretManager,
    ) -> None:
        self._repository = repository
        self._secret_manager = secret_manager

    def execute(self, data: ConnectionProfileInput) -> ConnectionProfile:
        encrypted_password = (
            self._secret_manager.encrypt(data.password) if data.password else None
        )
        profile = ConnectionProfile(
            id=str(uuid4()),
            name=data.name,
            description=data.description,
            server_address=data.server_address,
            protocol=data.protocol,
            port=data.port,
            username=data.username,
            encrypted_password=encrypted_password,
            route_metric=data.route_metric,
            dns_servers=data.dns_servers,
            mtu=data.mtu,
            keepalive=data.keepalive,
            auto_reconnect=data.auto_reconnect,
            allow_multiple=data.allow_multiple,
            tags=data.tags,
            config_payload=data.config_payload,
        )
        return self._repository.save(profile)
