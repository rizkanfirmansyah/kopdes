from __future__ import annotations

from abc import ABC, abstractmethod

from kopdes.domain.entities.connection_profile import ConnectionProfile
from kopdes.domain.entities.connection_session import ConnectionSession
from kopdes.domain.entities.event_log import EventLog
from kopdes.domain.entities.port_mapping import PortMapping


class ConnectionProfileRepository(ABC):
    @abstractmethod
    def save(self, profile: ConnectionProfile) -> ConnectionProfile:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[ConnectionProfile]:
        raise NotImplementedError

    @abstractmethod
    def get_by_name(self, name: str) -> ConnectionProfile | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, profile_id: str) -> ConnectionProfile | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, profile_id: str) -> None:
        raise NotImplementedError


class ConnectionSessionRepository(ABC):
    @abstractmethod
    def save(self, session: ConnectionSession) -> ConnectionSession:
        raise NotImplementedError

    @abstractmethod
    def list_latest(self) -> list[ConnectionSession]:
        raise NotImplementedError


class EventLogRepository(ABC):
    @abstractmethod
    def append(self, event: EventLog) -> EventLog:
        raise NotImplementedError

    @abstractmethod
    def list_recent(self, limit: int = 200) -> list[EventLog]:
        raise NotImplementedError


class PortMappingRepository(ABC):
    @abstractmethod
    def save(self, mapping: PortMapping) -> PortMapping:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[PortMapping]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, mapping_id: str) -> PortMapping | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_name(self, name: str) -> PortMapping | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, mapping_id: str) -> None:
        raise NotImplementedError
