from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Client, Coach
from bot.texts import msg_text, btn_text


@lru_cache(maxsize=None)
def genders_map(lang: str) -> dict[str, str]:
    return {"male": btn_text("male", lang), "female": btn_text("female", lang)}


@lru_cache(maxsize=None)
def verification_status_map(lang: str) -> dict[bool, str]:
    return {True: msg_text("verified", lang), False: msg_text("not_verified", lang)}


@lru_cache(maxsize=None)
def client_params_map(lang: str) -> dict[str, str]:
    return {
        "male": btn_text("male", lang),
        "female": btn_text("female", lang),
        "enabled": btn_text("enabled", lang),
        "disabled": btn_text("disabled", lang),
        "waiting_for_subscription": msg_text("waiting_for_subscription", lang),
        "waiting_for_program": msg_text("waiting_for_program", lang),
        "default": msg_text("client_default_status", lang),
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


def get_profile_attributes(role: str, user: Optional[Client | Coach], lang: str) -> dict[str, str]:
    def attr(name: str) -> str:
        val = getattr(user, name, "") if user else ""
        return str(val) if val is not None else ""

    if role == "client":
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

    verified_value = bool(getattr(user, "verified", False) if user else False)
    return {
        "name": attr("name"),
        "experience": attr("work_experience"),
        "notes": attr("additional_info"),
        "payment_details": attr("payment_details_plain"),
        "subscription_price": attr("subscription_price"),
        "program_price": attr("program_price"),
        "payout_due": attr("payout_due"),
        "verif_status": verification_status_map(lang).get(verified_value, msg_text("not_verified", lang)),
    }


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    mapping: dict[str, tuple[State, str]] = {
        "workout_experience": (States.workout_experience, msg_text("workout_experience", lang)),
        "workout_goals": (States.workout_goals, msg_text("workout_goals", lang)),
        "weight": (States.weight, msg_text("weight", lang)),
        "health_notes": (States.health_notes, msg_text("health_notes", lang)),
        "work_experience": (States.work_experience, msg_text("work_experience", lang)),
        "additional_info": (States.additional_info, msg_text("additional_info", lang)),
        "payment_details": (States.payment_details, msg_text("payment_details", lang)),
        "subscription_price": (States.subscription_price, msg_text("enter_subscription_price", lang)),
        "program_price": (States.program_price, msg_text("enter_program_price", lang)),
        "photo": (States.profile_photo, msg_text("upload_photo", lang)),
    }
    return mapping.get(callback, (States.name, ""))


async def get_client_page(
    client: Client,
    lang_code: str,
    subscription: bool,
    data: dict[str, Any],
) -> dict[str, Any]:
    params = client_params_map(lang_code)
    gender_key = (client.gender or "").strip().lower()

    from core.services import ProfileService

    profile = await ProfileService.get_profile(client.profile)
    page = {
        "name": client.name,
        "gender": params.get(gender_key, ""),
        "born_in": client.born_in,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
        "health_notes": client.health_notes,
        "weight": client.weight,
        "language": profile.language if profile and hasattr(profile, "language") else "",
        "subscription": params.get("enabled") if subscription else params.get("disabled"),
        "status": params.get(client.status, ""),
    }
    if data.get("new_client"):
        page["status"] = params["waiting_for_text"]
    return page


async def format_new_client_message(
    data: dict[str, Any],
    coach_lang: str,
    client_lang: str,
    preferable_type: str,
) -> str:
    if data.get("new_client"):
        return msg_text("new_client", coach_lang).format(lang=client_lang, workout_type=preferable_type)
    service = service_types_map(coach_lang).get(data.get("service_type", ""), "")
    return msg_text("incoming_request", coach_lang).format(
        service=service, lang=client_lang, workout_type=preferable_type
    )


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
