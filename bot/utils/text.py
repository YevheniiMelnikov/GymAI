from functools import lru_cache
from typing import Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Profile
from bot.texts import ButtonText, MessageText, translate


@lru_cache(maxsize=None)
def genders_map(lang: str) -> dict[str, str]:
    return {"male": translate(ButtonText.male, lang), "female": translate(ButtonText.female, lang)}


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
        "waiting_for_subscription": translate(MessageText.waiting_for_subscription, lang),
        "waiting_for_program": translate(MessageText.waiting_for_program, lang),
        "default": translate(MessageText.default_status, lang),
        "waiting_for_text": translate(MessageText.waiting_for_text, lang),
    }


@lru_cache(maxsize=None)
def service_types_map(lang: str) -> dict[str, str]:
    return {
        "subscription": translate(ButtonText.subscription, lang),
        "program": translate(ButtonText.program, lang),
    }


@lru_cache(maxsize=None)
def days_of_week_map(lang: str) -> dict[str, str]:
    return {
        "monday": translate(ButtonText.monday, lang),
        "tuesday": translate(ButtonText.tuesday, lang),
        "wednesday": translate(ButtonText.wednesday, lang),
        "thursday": translate(ButtonText.thursday, lang),
        "friday": translate(ButtonText.friday, lang),
        "saturday": translate(ButtonText.saturday, lang),
        "sunday": translate(ButtonText.sunday, lang),
    }


def get_profile_attributes(user: Optional[Profile], lang: str) -> dict[str, str]:
    def attr(name: str) -> str:
        val = getattr(user, name, "") if user else ""
        return str(val) if val is not None else ""

    gender_key = attr("gender").strip().lower().split(".", 1)[-1]
    return {
        "name": attr("name"),
        "gender": genders_map(lang).get(gender_key, ""),
        "born_in": attr("born_in"),
        "experience": attr("workout_experience"),
        "goals": attr("workout_goals"),
        "weight": attr("weight"),
        "notes": attr("health_notes"),
    }


StateMessageKey = tuple[State, MessageText | None]

_STATE_MESSAGE_KEYS: dict[str, StateMessageKey] = {
    "workout_experience": (States.workout_experience, MessageText.workout_experience),
    "workout_goals": (States.workout_goals, MessageText.workout_goals),
    "weight": (States.weight, MessageText.weight),
    "health_notes": (States.health_notes, MessageText.health_notes),
}


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    state, msg_key = _STATE_MESSAGE_KEYS.get(callback, (States.name, None))
    message = translate(msg_key, lang) if msg_key else ""
    return state, message


@lru_cache(maxsize=None)
def get_workout_types(lang: str) -> dict[str, str]:
    return {
        "home": translate(ButtonText.home_workout, lang),
        "gym": translate(ButtonText.gym_workout, lang),
    }


def get_translated_week_day(lang_code: str, day: str | None) -> str:
    if day is None:
        return ""
    return days_of_week_map(lang_code).get(day, "")
