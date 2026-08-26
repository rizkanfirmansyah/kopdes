from pathlib import Path

from kopdes.application.dtos.connection_profile_dto import ConnectionProfileInput
from kopdes.application.use_cases.bootstrap_database import bootstrap_database
from kopdes.application.use_cases.save_connection_profile import SaveConnectionProfileUseCase
from kopdes.infrastructure.db.models.connection_profile import ConnectionProfileModel
from kopdes.infrastructure.db.models.connection_session import ConnectionSessionModel
from kopdes.infrastructure.db.models.event_log import EventLogModel
from kopdes.infrastructure.db.models.health_check import HealthCheckModel
from kopdes.infrastructure.db.models.route_policy import RoutePolicyModel
from kopdes.infrastructure.db.models.tag import ProfileTagModel, TagModel
from kopdes.infrastructure.db.repositories.connection_profile_repository import (
    SqlAlchemyConnectionProfileRepository,
)
from kopdes.infrastructure.db.session import create_session_factory
from kopdes.infrastructure.security.crypto import SecretManager
from kopdes.shared.enums import ProtocolType


def test_connection_profile_repository_persists_encrypted_password(tmp_path: Path) -> None:
    db_path = tmp_path / "kopdes.db"
    database_url = f"sqlite:///{db_path}"
    bootstrap_database(database_url)
    repository = SqlAlchemyConnectionProfileRepository(create_session_factory(database_url))
    use_case = SaveConnectionProfileUseCase(
        repository=repository,
        secret_manager=SecretManager(tmp_path / "secret.key"),
    )

    use_case.execute(
        ConnectionProfileInput(
            name="VPN-TEST",
            description="integration test",
            server_address="1.2.3.4",
            protocol=ProtocolType.OPENVPN,
            username="tester",
            password="plain-password",
            tags=["integration"],
        )
    )

    stored = repository.get_by_name("VPN-TEST")
    assert stored is not None
    assert stored.encrypted_password is not None
    assert stored.encrypted_password != "plain-password"
    assert stored.tags == ["integration"]
