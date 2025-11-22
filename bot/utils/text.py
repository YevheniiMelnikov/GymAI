from functools import lru_cache
from typing import Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Profile
from bot.texts import msg_text, btn_text


@lru_cache(maxsize=None)
def genders_map(lang: str) -> dict[str, str]:
    return {"male": btn_text("male", lang), "female": btn_text("female", lang)}


@lru_cache(maxsize=None)
def verification_status_map(lang: str) -> dict[bool, str]:
    return {True: msg_text("verified", lang), False: msg_text("not_verified", lang)}


@lru_cache(maxsize=None)
def profile_params_map(lang: str) -> dict[str, str]:
    return {
        "male": btn_text("male", lang),
        "female": btn_text("female", lang),
        "enabled": btn_text("enabled", lang),
        "disabled": btn_text("disabled", lang),
        "waiting_for_subscription": msg_text("waiting_for_subscription", lang),
        "waiting_for_program": msg_text("waiting_for_program", lang),
        "default": msg_text("default_status", lang),
        "waiting_for_text": msg_text("waiting_for_text", lang),
    }


@lru_cache(maxsize=None)
def service_types_map(lang: str) -> dict[str, str]:
    return {
        "subscription": btn_text("subscription", lang),
        "program": btn_text("program", lang),
    }


@lru_cache(maxsize=None)
def days_of_week_map(lang: str) -> dict[str, str]:
    return {
        "monday": btn_text("monday", lang),
        "tuesday": btn_text("tuesday", lang),
        "wednesday": btn_text("wednesday", lang),
        "thursday": btn_text("thursday", lang),
        "friday": btn_text("friday", lang),
        "saturday": btn_text("saturday", lang),
        "sunday": btn_text("sunday", lang),
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


StateMessageKey = tuple[State, str]

_STATE_MESSAGE_KEYS: dict[str, StateMessageKey] = {
    "workout_experience": (States.workout_experience, "workout_experience"),
    "workout_goals": (States.workout_goals, "workout_goals"),
    "weight": (States.weight, "weight"),
    "health_notes": (States.health_notes, "health_notes"),
}


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    state, msg_key = _STATE_MESSAGE_KEYS.get(callback, (States.name, ""))
    message = msg_text(msg_key, lang) if msg_key else ""
    return state, message


@lru_cache(maxsize=None)
def get_workout_types(lang: str) -> dict[str, str]:
    return {
        "home": btn_text("home_workout", lang),
        "gym": btn_text("gym_workout", lang),
    }


def get_translated_week_day(lang_code: str, day: str | None) -> str:
    if day is None:
        return ""
    return days_of_week_map(lang_code).get(day, "")
