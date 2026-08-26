from __future__ import annotations

from kopdes.application.ports.repositories import ConnectionProfileRepository
from kopdes.domain.entities.connection_profile import ConnectionProfile


class ListConnectionProfilesUseCase:
    def __init__(self, repository: ConnectionProfileRepository) -> None:
        self._repository = repository

    def execute(self) -> list[ConnectionProfile]:
        return self._repository.list_all()
