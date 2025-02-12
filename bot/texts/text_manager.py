import os

import yaml

from bot.texts.resources import ButtonText, MessageText
from common.settings import settings

ResourceType = str | MessageText | ButtonText

if os.getenv("ENVIRONMENT", "local") == "local":
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RESOURCES = {
        "messages": f"{PROJECT_ROOT}/texts/messages.yml",
        "buttons": f"{PROJECT_ROOT}/texts/buttons.yml",
        "commands": f"{PROJECT_ROOT}/texts/commands.yml",
    }
else:
    RESOURCES = {
        "messages": "/opt/bot/texts/messages.yml",
        "buttons": "/opt/bot/texts/buttons.yml",
        "commands": "/opt/bot/texts/commands.yml",
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

    def get_text(self, key: ResourceType, lang: str | None = "eng") -> str | None:  # TODO: REMOVE
        if str(key) in self.messages:
            return self.messages[str(key)][lang]
        else:
            raise ValueError(f"Key {key.name} not found")


resource_manager = TextManager()


def msg_text(key: str, lang: str | None) -> str:
    return resource_manager.get_message(key, lang)


def btn_text(key: str, lang: str | None) -> str:
    return resource_manager.get_button(key, lang)


def translate(key: ResourceType, lang: str | None) -> str | None:  # TODO: REMOVE
    return resource_manager.get_text(key, lang)
