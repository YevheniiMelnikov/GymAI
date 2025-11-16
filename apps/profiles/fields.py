from django.db.models import CharField
from django.utils.translation import gettext_lazy as _

from core.encryptor import Encryptor


class EncryptedField(CharField):
    description = _("Encrypted string")  # pyrefly: ignore[bad-override]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 2048)
        super().__init__(*args, **kwargs)

    @staticmethod
    def from_db_value(value, expression, connection):
        if value is None:
            return value
        return Encryptor.decrypt(value)

    def to_python(self, value):
        if value is None or isinstance(value, str):
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return value
        return Encryptor.encrypt(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length", None) == 2048:
            kwargs.pop("max_length")
        return name, path, args, kwargs
