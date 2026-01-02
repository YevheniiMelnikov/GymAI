from enum import Enum
from pathlib import Path

import yaml

from bot.texts.resources import ButtonText, MessageText
from config.app_settings import settings

TextResourceKey = MessageText | ButtonText | str


class TextManager:
    _TEXTS_DIR = Path(__file__).parent.parent / "texts"
    _RESOURCES = {
        "messages": _TEXTS_DIR / "messages.yml",
        "buttons": _TEXTS_DIR / "buttons.yml",
        "commands": _TEXTS_DIR / "commands.yml",
    }
    messages: dict[str, dict[str, str]] = {}
    buttons: dict[str, dict[str, str]] = {}
    commands: dict[str, dict[str, str]] = {}

    @staticmethod
    def _resolve_resource_key(key: TextResourceKey) -> str:
        if isinstance(key, Enum):
            return key.value
        return key

    @classmethod
    def load_resources(cls) -> None:
        for resource_type, path in cls._RESOURCES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                if resource_type == "messages":
                    cls.messages = data  # pyrefly: ignore[bad-assignment]
                elif resource_type == "buttons":
                    cls.buttons = data  # pyrefly: ignore[bad-assignment]
                elif resource_type == "commands":
                    cls.commands = data  # pyrefly: ignore[bad-assignment]

    @staticmethod
    def get_message(key: TextResourceKey, lang: str | None) -> str:
        lang = lang or settings.DEFAULT_LANG
        try:
            return TextManager.messages[TextManager._resolve_resource_key(key)][lang]
        except KeyError as e:
            raise ValueError(f"Message key '{key}' ({lang}) not found") from e

    @staticmethod
    def get_button(key: TextResourceKey, lang: str | None) -> str:
        lang = lang or settings.DEFAULT_LANG
        try:
            return TextManager.buttons[TextManager._resolve_resource_key(key)][lang]
        except KeyError as e:
            raise ValueError(f"Button key '{key}' ({lang}) not found") from e


def translate(text_key: TextResourceKey, lang: str | None) -> str:
    if isinstance(text_key, MessageText):
        return TextManager.get_message(text_key, lang)
    return TextManager.get_button(text_key, lang)
