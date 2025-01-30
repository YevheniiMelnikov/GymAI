from cryptography.fernet import Fernet

from core.settings import settings


class Encrypter:
    def __init__(self, key: str):
        self.key = key
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self.cipher.decrypt(ciphertext.encode()).decode()


def generate_key() -> str:
    return Fernet.generate_key().decode()


encrypter = Encrypter(settings.CRYPTO_KEY)
