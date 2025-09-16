import sys
import importlib
import types

import conftest

settings_mod = sys.modules.get("config.app_settings")
if settings_mod is None:
    settings_mod = types.ModuleType("config.app_settings")
    sys.modules["config.app_settings"] = settings_mod

settings_mod.settings = types.SimpleNamespace(**conftest.settings_stub.__dict__)


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
