from functools import lru_cache
from typing import Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Profile
from bot.texts import ButtonText, MessageText, translate


@lru_cache(maxsize=None)
def verification_status_map(lang: str) -> dict[bool, str]:
    return {True: translate(MessageText.verified, lang), False: translate(MessageText.not_verified, lang)}


@lru_cache(maxsize=None)
def profile_params_map(lang: str) -> dict[str, str]:
    return {
        "male": translate(ButtonText.male, lang),
        "female": translate(ButtonText.female, lang),
        "enabled": translate(ButtonText.enabled, lang),
        "disabled": translate(ButtonText.disabled, lang),
        "created": translate(MessageText.waiting_for_text, lang),
        "completed": translate(MessageText.default_status, lang),
    }


@lru_cache(maxsize=None)
def service_types_map(lang: str) -> dict[str, str]:
    return {
        "subscription": translate(ButtonText.subscription, lang),
        "program": translate(ButtonText.program, lang),
    }


def get_profile_attributes(user: Optional[Profile], lang: str) -> dict[str, str]:
    def attr(name: str) -> str:
        val = getattr(user, name, "") if user else ""
        return str(val) if val is not None else ""

    location_key = attr("workout_location").strip().lower()
    workout_locations = get_workout_locations(lang)
    return {
        "born_in": attr("born_in"),
        "experience": attr("workout_experience"),
        "goals": attr("workout_goals"),
        "workout_location": workout_locations.get(location_key, "") if location_key else "",
        "weight": attr("weight"),
        "height": attr("height"),
        "notes": attr("health_notes"),
    }


StateMessageKey = tuple[State, MessageText | None]

_STATE_MESSAGE_KEYS: dict[str, StateMessageKey] = {
    "workout_experience": (States.workout_experience, MessageText.workout_experience),
    "workout_goals": (States.workout_goals, MessageText.workout_goals),
    "workout_location": (States.workout_location, MessageText.workout_location),
    "weight": (States.weight, MessageText.weight),
    "height": (States.height, MessageText.height),
    "health_notes": (States.health_notes_choice, MessageText.health_notes_question),
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
