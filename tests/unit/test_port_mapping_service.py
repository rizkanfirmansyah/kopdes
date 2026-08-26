from datetime import datetime, timezone
from pathlib import Path

from kopdes.application.dtos.connection_profile_dto import PortMappingInput
from kopdes.application.dtos.runtime_state import ActionResult, PortMappingSession
from kopdes.application.services.control_center_service import ControlCenterService
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.shared.enums import ConnectionStatus


class ProfileRepository:
    def list_all(self):
        return []

    def get_by_id(self, _profile_id):
        return None

    def get_by_name(self, _name):
        return None


class SessionRepository:
    def list_latest(self):
        return []


class EventRepository:
    def append(self, event):
        return event

    def list_recent(self, limit=200):
        return []


class MappingRepository:
    def __init__(self):
        self.items: dict[str, PortMapping] = {}

    def save(self, mapping):
        self.items[mapping.id] = mapping
        return mapping

    def list_all(self):
        return sorted(self.items.values(), key=lambda item: item.name)

    def get_by_id(self, mapping_id):
        return self.items.get(mapping_id)

    def get_by_name(self, name):
        return next((item for item in self.items.values() if item.name == name), None)

    def delete(self, mapping_id):
        self.items.pop(mapping_id, None)


class TunnelManager:
    def __init__(self):
        self.sessions: list[PortMappingSession] = []
        self.passwords: list[str | None] = []

    def start(self, mapping, password=None):
        self.passwords.append(password)
        self.sessions = [
            PortMappingSession(mapping.id, mapping.name, "active", 1000 + len(self.sessions), True)
        ]
        return ActionResult(True, "SSH mapping started.")

    def stop(self, _mapping_id):
        self.sessions = []
        return ActionResult(True, "SSH mapping stopped.")

    def list_sessions(self):
        return self.sessions

    def shutdown(self, _mappings):
        self.sessions = []
        return ActionResult(True, "Stopped mappings.")


def build_service(tmp_path: Path):
    mappings = MappingRepository()
    manager = TunnelManager()
    service = ControlCenterService(
        ProfileRepository(),
        SessionRepository(),
        EventRepository(),
        SecretManager(tmp_path / "secret.key"),
        object(),
        object(),
        object(),
        object(),
        object(),
        object(),
        mappings,
        manager,
    )
    return service, mappings, manager


def input_data(name="Postgres 5433", local_port=5433, password="db-secret"):
    return PortMappingInput(
        name=name,
        description="Forward PostgreSQL through the jump host",
        ssh_host="192.168.0.10",
        ssh_username="boss",
        ssh_port=22,
        local_host="127.0.0.1",
        local_port=local_port,
        remote_host="127.0.0.1",
        remote_port=5432,
        password=password,
    )


def test_save_encrypts_password_and_edit_preserves_it(tmp_path: Path) -> None:
    service, mappings, _manager = build_service(tmp_path)

    saved = service.save_port_mapping(input_data())
    encrypted = saved.encrypted_password
    assert encrypted is not None
    assert encrypted != "db-secret"
    assert "db-secret" not in encrypted

    updated = service.save_port_mapping(input_data(local_port=5434, password=None), saved.id)

    assert updated.encrypted_password == encrypted
    assert mappings.get_by_id(saved.id).local_port == 5434


def test_connect_passes_decrypted_password_and_reports_active_mapping(tmp_path: Path) -> None:
    service, _mappings, manager = build_service(tmp_path)
    saved = service.save_port_mapping(input_data())

    result = service.connect_port_mapping(saved.id)
    rows = service.list_port_mapping_rows()

    assert result.success is True
    assert manager.passwords == ["db-secret"]
    assert rows[0].status == ConnectionStatus.ACTIVE
    assert rows[0].local_endpoint == "127.0.0.1:5433"
    assert rows[0].remote_endpoint == "127.0.0.1:5432"


def test_multiple_mappings_are_listed_independently(tmp_path: Path) -> None:
    service, _mappings, manager = build_service(tmp_path)
    first = service.save_port_mapping(input_data("Postgres 5433", 5433, None))
    second = service.save_port_mapping(input_data("Postgres 5434", 5434, None))
    manager.sessions = [
        PortMappingSession(first.id, first.name, "active", 2001, True),
        PortMappingSession(second.id, second.name, "active", 2002, True),
    ]

    rows = service.list_port_mapping_rows()

    assert [row.name for row in rows] == ["Postgres 5433", "Postgres 5434"]
    assert [row.pid for row in rows] == [2001, 2002]


def test_started_mapping_without_process_is_failed(tmp_path: Path) -> None:
    service, mappings, _manager = build_service(tmp_path)
    saved = service.save_port_mapping(input_data(password=None))
    saved.last_started_at = datetime.now(timezone.utc)
    mappings.save(saved)

    rows = service.list_port_mapping_rows()

    assert rows[0].status == ConnectionStatus.FAILED
    assert "not running" in rows[0].last_error
