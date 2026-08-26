from pathlib import Path

from kopdes.infrastructure.security.crypto import SecretManager


def test_secret_manager_encrypts_and_decrypts(tmp_path: Path) -> None:
    manager = SecretManager(tmp_path / "secret.key")
    ciphertext = manager.encrypt("super-secret")
    assert ciphertext != "super-secret"
    assert manager.decrypt(ciphertext) == "super-secret"
