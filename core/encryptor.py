import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet

from loguru import logger
from config.env_settings import Settings


class Encryptor:
    _fernet = None

    @classmethod
    def _get_fernet(cls):
        if cls._fernet is None:
            key = hashlib.sha256(Settings.API_KEY.encode()).digest()
            fernet_key = base64.urlsafe_b64encode(key)
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
