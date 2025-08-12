import sys
import importlib


class DummyFernet:
    def __init__(self, key):
        pass

    def encrypt(self, data: bytes) -> bytes:
        return b"x" + data

    def decrypt(self, token: bytes) -> bytes:
        return token[1:]


sys.modules["cryptography.fernet"].Fernet = DummyFernet
Encryptor = importlib.reload(__import__("core.encryptor", fromlist=["Encryptor"])).Encryptor


def test_encrypt_decrypt_roundtrip():
    text = "secret-data"
    token = Encryptor.encrypt(text)
    assert token != text
    assert Encryptor.decrypt(token) == text
