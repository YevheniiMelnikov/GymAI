from functools import lru_cache
from aiogram.fsm.state import State

from bot.states import States
from bot.texts import ButtonText, MessageText, translate
from config.app_settings import settings


StateMessageKey = tuple[State, MessageText | None]

_STATE_MESSAGE_KEYS: dict[str, StateMessageKey] = {
    "workout_experience": (States.workout_experience, MessageText.workout_experience),
    "workout_goals": (States.workout_goals, MessageText.workout_goals),
    "workout_location": (States.workout_location, MessageText.workout_location),
    "weight": (States.weight, MessageText.weight),
    "height": (States.height, MessageText.height),
    "health_notes": (States.health_notes_choice, MessageText.health_notes_question),
    "diet_allergies": (States.diet_allergies_choice, MessageText.diet_allergies_question),
    "diet_products": (States.diet_products, MessageText.diet_products),
}


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    state, msg_key = _STATE_MESSAGE_KEYS.get(callback, (States.gender, None))
    message = translate(msg_key, lang) if msg_key else ""
    return state, message


@lru_cache(maxsize=None)
def get_workout_locations(lang: str) -> dict[str, str]:
    return {
        "home": translate(ButtonText.home_workout, lang),
        "gym": translate(ButtonText.gym_workout, lang),
    }


@lru_cache(maxsize=None)
def get_workout_experience_levels(lang: str) -> dict[str, str]:
    return {
        "beginner": translate(ButtonText.beginner, lang),
        "amateur": translate(ButtonText.intermediate, lang),
        "advanced": translate(ButtonText.advanced, lang),
        "pro": translate(ButtonText.experienced, lang),
        "0-1": translate(ButtonText.beginner, lang),
        "1-3": translate(ButtonText.intermediate, lang),
        "3-5": translate(ButtonText.advanced, lang),
        "5+": translate(ButtonText.experienced, lang),
    }


def normalize_support_contact(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return value
    if value.startswith("@"):
        value = value[1:]
    if value.startswith("t.me/") or value.startswith("telegram.me/"):
        return f"https://{value}"
    return f"https://t.me/{value}"


def support_contact_url() -> str:
    return normalize_support_contact(settings.TG_SUPPORT_CONTACT) or settings.TG_SUPPORT_CONTACT or ""
