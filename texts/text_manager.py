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
    payment_required = auto()
    payment_success = auto()
    subscription_page = auto()
    update_your_data = auto()
    coach_info_message = auto()
    enter_your_message = auto()
    enter_daily_program = auto()
    enter_exercise = auto()
    enter_sets = auto()
    enter_reps = auto()
    exercise_weight = auto()
    program_guide = auto()
    payment_link = auto()
    workout_feedback = auto()
    workout_completed = auto()
    continue_editing = auto()
    select_exercise = auto()
    parameter_to_edit = auto()
    delete_confirmation = auto()

    name = auto()
    choose_gender = auto()
    birth_date = auto()
    workout_goals = auto()
    weight = auto()
    workout_experience = auto()
    health_notes = auto()
    work_experience = auto()
    workout_type = auto()
    payment_details = auto()
    additional_info = auto()
    upload_photo = auto()
    photo_uploaded = auto()
    coach_verified = auto()
    message_sent = auto()
    workouts_number = auto()
    workouts_per_week = auto()
    select_days = auto()
    select_service = auto()

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
    no_exercises_to_save = auto()
    email_unavailable = auto()
    program_not_ready = auto()
    complete_all_days = auto()
    questionnaire_not_completed = auto()
    image_error = auto()
    payment_failure = auto()
    unable_to_delete_profile = auto()

    coach_page = auto()
    client_page = auto()
    saved = auto()
    gift = auto()
    wait_for_verification = auto()
    verified = auto()
    not_verified = auto()
    your_data_updated = auto()
    waiting = auto()
    waiting_for_text = auto()
    program_compiled = auto()
    feedback = auto()
    password_retype = auto()
    password_reset_sent = auto()
    feedback_sent = auto()
    registration_successful = auto()
    new_coach_request = auto()
    new_client = auto()
    have_you_trained = auto()
    workout_results = auto()
    keep_going = auto()
    workout_description = auto()
    incoming_message = auto()
    incoming_request = auto()
    new_program = auto()
    main_menu = auto()
    help = auto()
    program_page = auto()
    start = auto()
    signed_in = auto()
    logout = auto()
    profile_deleted = auto()
    accept_policy = auto()
    contract_info_message = auto()

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
    edit = auto()
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
    add_exercise = auto()
    save = auto()
    next_day = auto()
    reset_program = auto()
    answer = auto()
    done = auto()
    get = auto()
    gym_workout = auto()
    home_workout = auto()
    street_workout = auto()
    later = auto()
    enabled = auto()
    disabled = auto()
    monday = auto()
    tuesday = auto()
    wednesday = auto()
    thursday = auto()
    friday = auto()
    saturday = auto()
    sunday = auto()
    answer_yes = auto()
    answer_no = auto()
    edit_exercise = auto()
    delete_exercise = auto()
    contact_coach = auto()
    sets = auto()
    reps = auto()
    exercises = auto()
    view = auto()
    create = auto()
    prev_menu = auto()
    delete = auto()

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
    if lang is None:
        lang = "ua"
    return resource_manager.get_text(key, lang)
