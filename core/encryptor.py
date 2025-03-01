from cryptography.fernet import Fernet

from common.settings import settings


class Encryptor:  # TODO: USE FOR SENSITIVE DATA DB FIELDS
    cipher = Fernet(settings.CRYPTO_KEY)

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        return cls.cipher.encrypt(plaintext.encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        return cls.cipher.decrypt(ciphertext.encode()).decode()
