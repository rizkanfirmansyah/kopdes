from pathlib import Path

from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.domain.entities.port_mapping import PortMapping
from kopdes.infrastructure.db.repositories.port_mapping_repository import (
    SqlAlchemyPortMappingRepository,
)
from kopdes.infrastructure.db.session import create_session_factory


def test_port_mapping_repository_round_trip(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'kopdes.db'}"
    bootstrap_database(database_url)
    repository = SqlAlchemyPortMappingRepository(create_session_factory(database_url))
    mapping = PortMapping(
        id="mapping-1",
        name="PostgreSQL",
        description="Local database forward",
        ssh_host="192.168.0.10",
        ssh_username="boss",
        local_port=5433,
        remote_host="localhost",
        remote_port=5432,
        encrypted_password="encrypted-value",
    )

    saved = repository.save(mapping)

    assert repository.get_by_id(mapping.id).name == "PostgreSQL"
    assert repository.get_by_name("PostgreSQL").encrypted_password == "encrypted-value"
    assert repository.list_all()[0].local_port == 5433
    repository.delete(saved.id)
    assert repository.get_by_id(saved.id) is None
