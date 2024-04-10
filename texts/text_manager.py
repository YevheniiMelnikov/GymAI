from enum import Enum, auto

import yaml

from common import settings


class MessageText(Enum):
    welcome = auto()
    choose_language = auto()
    choose_short_name = auto()
    choose_password = auto()
    invalid_content = auto()
    choose_gender = auto()
    choose_account_type = auto()
    choose_birth_date = auto()
    registration_successful = auto()

    def __str__(self) -> str:
        return f"messages.{self.name}"


class ButtonText(Enum):
    female = auto()
    male = auto()
    client = auto()
    coach = auto()

    def __str__(self) -> str:
        return f"buttons.{self.name}"


ResourceType = str | MessageText | ButtonText


class TextManager:
    def __init__(self) -> None:
        self.messages = self.load_messages()

    def get_text(self, key: ResourceType, lang: str | None = "eng") -> str | None:
        if str(key) in self.messages:
            return self.messages[str(key)][lang]
        else:
            raise ValueError(f"Key {key.name} not found")

    @staticmethod
    def load_messages() -> dict[str, dict[str, str]]:
        result = {}
        for type, path in settings.MESSAGES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
            for key, value in data.items():
                result[f"{type}.{key}"] = value
        return result


resource_manager = TextManager()


def translate(key: ResourceType, lang: str | None = "ua") -> str | None:  # TODO: MOVE TO FUNCTIONS
    return resource_manager.get_text(key, lang)
