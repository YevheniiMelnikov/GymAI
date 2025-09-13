import base64
import hashlib
from importlib import import_module
from typing import Any, ClassVar, Optional

from loguru import logger
from config.app_settings import settings


class Encryptor:
    _fernet: ClassVar[Optional[Any]] = None

    @classmethod
    def _get_fernet(cls):
        if cls._fernet is None:
            key = hashlib.sha256(settings.API_KEY.encode()).digest()
            fernet_key = base64.urlsafe_b64encode(key)
            Fernet = getattr(import_module("cryptography.fernet"), "Fernet")
            cls._fernet = Fernet(fernet_key)
        return cls._fernet

    @classmethod
    def encrypt(cls, data: str) -> str:
        if not data:
            return data
        fernet = cls._get_fernet()
        encrypted_data = fernet.encrypt(data.encode())
        return encrypted_data.decode()

    @classmethod
    def decrypt(cls, token: str) -> Optional[str]:
        if not token:
            return None
        try:
            fernet = cls._get_fernet()
            decrypted_data = fernet.decrypt(token.encode())
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None
