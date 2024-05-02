import re
from functools import wraps

from aiogram.fsm.state import State
from typing import Optional

from bot.states import States
from common.models import Client, Coach
from texts.text_manager import ButtonText, MessageText, translate


def singleton(cls: type) -> object:
    instances = {}

    @wraps(cls)
    def get_instance(*args, **kwargs) -> object:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


def validate_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if not any(char.isdigit() for char in password):
        return False
    if not any(char.isalpha() for char in password):
        return False

    return True


def validate_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}$"
    return bool(re.match(pattern, email))


def validate_birth_date(date_str: str) -> bool:
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not pattern.match(date_str):
        return False

    year, month, day = map(int, date_str.split("-"))
    if not (1900 <= year <= 2100 and 1 <= month <= 12):
        return False

    if month in [4, 6, 9, 11] and day > 30:
        return False
    elif month == 2:
        if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) and day > 29:
            return False
        elif day > 28:
            return False

    return 1 <= day <= 31


def get_profile_attributes(role: str, user: Optional[Client | Coach], lang_code: str) -> dict[str, str]:
    genders = {
        "male": translate(ButtonText.male, lang=lang_code),
        "female": translate(ButtonText.female, lang=lang_code),
    }
    if role == "client":
        attributes = {
            "gender": genders[user.gender] if user and user.gender in genders else "",
            "birth_date": user.birth_date if user.birth_date else "",
            "experience": user.workout_experience if user.workout_experience else "",
            "goals": user.workout_goals if user.workout_goals else "",
            "weight": user.weight if user.weight else "",
            "notes": user.health_notes if user.health_notes else "",
        }
    else:
        attributes = {
            "name": user.name if user else "",
            "experience": user.experience if user else "",
            "notes": user.additional_info if user else "",
            "payment_details": user.payment_details if user else "",
        }
    return attributes



def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    return {
        "workout_experience": (States.workout_experience, translate(MessageText.workout_experience, lang=lang)),
        "workout_goals": (States.workout_goals, translate(MessageText.workout_goals, lang=lang)),
        "weight": (States.weight, translate(MessageText.weight, lang=lang)),
        "health_notes": (States.health_notes, translate(MessageText.health_notes, lang=lang)),
    }.get(callback, (None, None))
