from core.encryptor import Encryptor


def test_encrypt_decrypt_roundtrip():
    text = "secret-data"
    token = Encryptor.encrypt(text)
    assert token != text
    assert Encryptor.decrypt(token) == text
