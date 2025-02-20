from pathlib import Path

import yaml

from bot.texts.resources import ButtonText, MessageText
from common.settings import settings

ResourceType = str | MessageText | ButtonText

TEXTS_DIR = Path(__file__).parent.parent / "texts"
RESOURCES = {
    "messages": TEXTS_DIR / "messages.yml",
    "buttons": TEXTS_DIR / "buttons.yml",
    "commands": TEXTS_DIR / "commands.yml",
}


class TextManager:
    def __init__(self) -> None:
        self.messages = {}
        self.buttons = {}
        self.commands = {}
        self.load_resources()

    def load_resources(self) -> None:
        for resource_type, path in RESOURCES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                if resource_type == "messages":
                    self.messages = data
                elif resource_type == "buttons":
                    self.buttons = data
                elif resource_type == "commands":
                    self.commands = data

    def get_message(self, key: str, lang: str | None) -> str:
        lang = lang or settings.DEFAULT_BOT_LANGUAGE
        try:
            return self.messages[key][lang]
        except KeyError as e:
            raise ValueError(f"Message key '{key}' ({lang}) not found") from e

    def get_button(self, key: str, lang: str | None) -> str:
        lang = lang or settings.DEFAULT_BOT_LANGUAGE
        try:
            return self.buttons[key][lang]
        except KeyError as e:
            raise ValueError(f"Button key '{key}' ({lang}) not found") from e


resource_manager = TextManager()


def msg_text(msg_key: str, lang: str | None) -> str:
    return resource_manager.get_message(msg_key, lang)


def btn_text(btn_key: str, lang: str | None) -> str:
    return resource_manager.get_button(btn_key, lang)
