from enum import Enum, auto

import yaml

from common import settings


class MessageText(Enum):
    username = auto()
    password = auto()
    email = auto()
    client_profile = auto()
    coach_profile = auto()
    coach_selected = auto()
    choose_action = auto()
    choose_language = auto()
    choose_account_type = auto()
    edit_profile = auto()
    choose_profile_parameter = auto()
    update_your_data = auto()
    coach_info_message = auto()
    enter_your_message = auto()

    name = auto()
    choose_gender = auto()
    birth_date = auto()
    workout_goals = auto()
    weight = auto()
    workout_experience = auto()
    health_notes = auto()
    work_experience = auto()
    payment_details = auto()
    additional_info = auto()
    upload_photo = auto()
    photo_uploaded = auto()
    coach_verified = auto()
    message_sent = auto()

    invalid_credentials = auto()
    invalid_content = auto()
    unexpected_error = auto()
    password_mismatch = auto()
    password_requirements = auto()
    username_unavailable = auto()
    reset_password_offer = auto()
    no_profiles_found = auto()
    password_unsafe = auto()
    photo_upload_fail = auto()
    coach_declined = auto()
    no_program = auto()
    no_coaches = auto()
    out_of_range = auto()
    no_clients = auto()

    coach_page = auto()
    client_page = auto()
    saved = auto()
    wait_for_verification = auto()
    verified = auto()
    not_verified = auto()
    your_data_updated = auto()
    feedback = auto()
    password_retype = auto()
    password_reset_sent = auto()
    feedback_sent = auto()
    registration_successful = auto()
    new_coach_request = auto()
    incoming_message = auto()
    main_menu = auto()
    help = auto()
    start = auto()
    signed_in = auto()
    logout = auto()

    def __str__(self) -> str:
        return f"messages.{self.name}"


class ButtonText(Enum):
    female = auto()
    male = auto()
    client = auto()
    coach = auto()
    my_clients = auto()
    feedback = auto()
    my_profile = auto()
    my_program = auto()
    sign_in = auto()
    sign_up = auto()
    back = auto()
    quit = auto()
    forward = auto
    edit_profile = auto()
    program = auto()
    subscription = auto()
    choose_coach = auto()
    contact_client = auto()
    select = auto()
    beginner = auto()
    intermediate = auto()
    advanced = auto()
    experienced = auto()
    weight = auto()
    health_notes = auto()
    workout_goals = auto()
    workout_experience = auto()
    work_experience = auto()
    additional_info = auto()
    payment_details = auto()
    photo = auto()
    answer = auto()

    def __str__(self) -> str:
        return f"buttons.{self.name}"


ResourceType = str | MessageText | ButtonText


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
        for type, path in settings.RESOURCES.items():
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
            for key, value in data.items():
                result[f"{type}.{key}"] = value
        return result

    @staticmethod
    def load_commands() -> dict[str, dict[str, str]]:
        result = {}
        with open(settings.RESOURCES["commands"], "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
            for key, value in data.items():
                result[key] = value
        return result


resource_manager = TextManager()


def translate(key: ResourceType, lang: str | None = "ua") -> str | None:
    return resource_manager.get_text(key, lang)
