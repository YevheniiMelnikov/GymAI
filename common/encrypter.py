import os

from cryptography.fernet import Fernet


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


crypto_key = os.getenv("CRYPTO_KEY")
encrypter = Encrypter(crypto_key)
