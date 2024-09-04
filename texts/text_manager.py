import os

import yaml

from texts.resources import ButtonText, MessageText

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
        "messages": "/opt/texts/messages.yml",
        "buttons": "/opt/texts/buttons.yml",
        "commands": "/opt/texts/commands.yml",
    }


class TextManager:
    def __init__(self) -> None:
        self.messages = self.load_messages()
        self.commands = self.load_commands()

    def get_text(self, key: ResourceType, lang: str | None = "eng") -> str | None:
        if str(key) in self.messages:
            return self.messages[str(key)][lang]
        else:
            raise ValueError(f"Key {key.name} not found")

    @staticmethod
    def load_messages() -> dict[str, dict[str, str]]:
        result = {}
        for type, path in RESOURCES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
            for key, value in data.items():
                result[f"{type}.{key}"] = value
        return result

    @staticmethod
    def load_commands() -> dict[str, dict[str, str]]:
        result = {}
        with open(RESOURCES["commands"], "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
            for key, value in data.items():
                result[key] = value
        return result


resource_manager = TextManager()


def translate(key: ResourceType, lang: str | None = "ua") -> str | None:
    if lang is None:
        lang = "ua"
    return resource_manager.get_text(key, lang)
