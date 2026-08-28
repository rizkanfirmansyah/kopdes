from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet


LOGGER = logging.getLogger(__name__)


class SecretManager:
    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def encrypt(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    def _load_or_create_key(self) -> bytes:
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        if self._key_path.exists():
            key = self._key_path.read_bytes()
            try:
                os.chmod(self._key_path, 0o600)
            except OSError as exc:
                LOGGER.error("Could not secure existing KOPDES secret key %s", self._key_path)
                raise RuntimeError("KOPDES secret key permissions could not be secured.") from exc
            return key
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        os.chmod(self._key_path, 0o600)
        return key
