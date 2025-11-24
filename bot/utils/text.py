from functools import lru_cache
from typing import Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Profile
from bot.texts import ButtonText, MessageText, msg_text, btn_text


@lru_cache(maxsize=None)
def genders_map(lang: str) -> dict[str, str]:
    return {"male": btn_text(ButtonText.male, lang), "female": btn_text(ButtonText.female, lang)}


@lru_cache(maxsize=None)
def verification_status_map(lang: str) -> dict[bool, str]:
    return {True: msg_text(MessageText.verified, lang), False: msg_text(MessageText.not_verified, lang)}


@lru_cache(maxsize=None)
def profile_params_map(lang: str) -> dict[str, str]:
    return {
        "male": btn_text(ButtonText.male, lang),
        "female": btn_text(ButtonText.female, lang),
        "enabled": btn_text(ButtonText.enabled, lang),
        "disabled": btn_text(ButtonText.disabled, lang),
        "waiting_for_subscription": msg_text(MessageText.waiting_for_subscription, lang),
        "waiting_for_program": msg_text(MessageText.waiting_for_program, lang),
        "default": msg_text(MessageText.default_status, lang),
        "waiting_for_text": msg_text(MessageText.waiting_for_text, lang),
    }


@lru_cache(maxsize=None)
def service_types_map(lang: str) -> dict[str, str]:
    return {
        "subscription": btn_text(ButtonText.subscription, lang),
        "program": btn_text(ButtonText.program, lang),
    }


@lru_cache(maxsize=None)
def days_of_week_map(lang: str) -> dict[str, str]:
    return {
        "monday": btn_text(ButtonText.monday, lang),
        "tuesday": btn_text(ButtonText.tuesday, lang),
        "wednesday": btn_text(ButtonText.wednesday, lang),
        "thursday": btn_text(ButtonText.thursday, lang),
        "friday": btn_text(ButtonText.friday, lang),
        "saturday": btn_text(ButtonText.saturday, lang),
        "sunday": btn_text(ButtonText.sunday, lang),
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
    message = msg_text(msg_key, lang) if msg_key else ""
    return state, message


@lru_cache(maxsize=None)
def get_workout_types(lang: str) -> dict[str, str]:
    return {
        "home": btn_text(ButtonText.home_workout, lang),
        "gym": btn_text(ButtonText.gym_workout, lang),
    }


def get_translated_week_day(lang_code: str, day: str | None) -> str:
    if day is None:
        return ""
    return days_of_week_map(lang_code).get(day, "")
