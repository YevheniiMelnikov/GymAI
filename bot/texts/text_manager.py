from pathlib import Path

import yaml

from bot.texts.resources import ButtonText, MessageText
from config.env_settings import Settings

ResourceType = str | MessageText | ButtonText

TEXTS_DIR = Path(__file__).parent.parent / "texts"
RESOURCES = {
    "messages": TEXTS_DIR / "messages.yml",
    "buttons": TEXTS_DIR / "buttons.yml",
    "commands": TEXTS_DIR / "commands.yml",
}


class TextManager:
    messages: dict[str, dict[str, str]] = {}
    buttons: dict[str, dict[str, str]] = {}
    commands: dict[str, dict[str, str]] = {}

    @classmethod
    def load_resources(cls) -> None:
        for resource_type, path in RESOURCES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                if resource_type == "messages":
                    cls.messages = data
                elif resource_type == "buttons":
                    cls.buttons = data
                elif resource_type == "commands":
                    cls.commands = data

    @classmethod
    def get_message(cls, key: str, lang: str | None) -> str:
        lang = lang or Settings.BOT_LANG
        try:
            return cls.messages[key][lang]
        except KeyError as e:
            raise ValueError(f"Message key '{key}' ({lang}) not found") from e

    @classmethod
    def get_button(cls, key: str, lang: str | None) -> str:
        lang = lang or Settings.BOT_LANG
        try:
            return cls.buttons[key][lang]
        except KeyError as e:
            raise ValueError(f"Button key '{key}' ({lang}) not found") from e


TextManager.load_resources()


def msg_text(msg_key: str, lang: str | None) -> str:
    return TextManager.get_message(msg_key, lang)


def btn_text(btn_key: str, lang: str | None) -> str:
    return TextManager.get_button(btn_key, lang)
