from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class CustomPasswordValidator:
    def __init__(self):
        self.min_length = 8

    def validate(self, password: str, user=None) -> None:
        if len(password) < self.min_length:
            raise ValidationError(
                _("This password must contain at least %(min_length)d characters."),
                code="password_too_short",
                params={"min_length": self.min_length},
            )

        if not any(char.isdigit() for char in password):
            raise ValidationError(
                _("This password must contain at least one digit."),
                code="password_no_number",
            )

        if not any(char.isalpha() for char in password):
            raise ValidationError(
                _("This password must contain at least one letter."),
                code="password_no_letter",
            )

    def get_help_text(self) -> str:
        return _(
            "Ваш пароль повинен містити принаймні %(min_length)d символів,"
            "включаючи принаймні одну літеру та одну цифру." % {"min_length": self.min_length}
        )
