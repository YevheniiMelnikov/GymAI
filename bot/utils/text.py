from __future__ import annotations

from typing import Any, Optional, cast

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Client, Coach
from bot.texts import msg_text, btn_text


def genders(lang: str) -> dict[str, str]:
    return {"male": btn_text("male", lang), "female": btn_text("female", lang)}


def verification_status(lang: str) -> dict[bool, str]:
    return {True: msg_text("verified", lang), False: msg_text("not_verified", lang)}


def client_params(lang: str) -> dict[str, str]:
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


def service_types(lang: str) -> dict[str, str]:
    return {
        "subscription": btn_text("subscription", lang),
        "program": btn_text("program", lang),
    }


def workout_types(lang: str) -> dict[str, str]:
    return {
        "home": btn_text("home_workout", lang),
        "gym": btn_text("gym_workout", lang),
    }


def days_of_week(lang: str) -> dict[str, str]:
    return {
        "monday": btn_text("monday", lang),
        "tuesday": btn_text("tuesday", lang),
        "wednesday": btn_text("wednesday", lang),
        "thursday": btn_text("thursday", lang),
        "friday": btn_text("friday", lang),
        "saturday": btn_text("saturday", lang),
        "sunday": btn_text("sunday", lang),
    }


def state_msgs(callback: str, lang: str) -> tuple[State | None, str | None]:
    mapping = {
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
    return mapping.get(callback, (None, None))


def get_profile_attributes(status: str, user: Optional[Client | Coach], lang: str) -> dict[str, str]:
    def get(attr: str) -> str:
        val = getattr(user, attr, "") if user else ""
        return str(val) if val is not None else ""

    if status == "client":
        return {
            "name": get("name"),
            "gender": genders(lang).get(get("gender"), ""),
            "born_in": get("born_in"),
            "experience": get("workout_experience"),
            "goals": get("workout_goals"),
            "weight": get("weight"),
            "notes": get("health_notes"),
        }
    else:
        verified_value = getattr(user, "verified", False) if user else False
        if not isinstance(verified_value, bool):
            verified_value = bool(verified_value)
        return {
            "name": get("name"),
            "experience": get("work_experience"),
            "notes": get("additional_info"),
            "payment_details": get("payment_details_plain"),
            "subscription_price": get("subscription_price"),
            "program_price": get("program_price"),
            "verif_status": verification_status(lang).get(verified_value, msg_text("not_verified", lang)),
        }


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    state_msg = state_msgs(callback, lang)
    if state_msg[0] is None or state_msg[1] is None:
        return States.name, ""
    return cast(tuple[State, str], state_msg)


async def get_client_page(client: Client, lang_code: str, subscription: bool, data: dict[str, Any]) -> dict[str, Any]:
    params = client_params(lang_code)
    from core.services.profile_service import ProfileService

    client_profile = await ProfileService.get_profile(client.profile)
    page = {
        "name": client.name,
        "gender": params.get(client.gender or "", ""),
        "born_in": client.born_in,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
        "health_notes": client.health_notes,
        "weight": client.weight,
        "language": client_profile.language if client_profile and hasattr(client_profile, "language") else "",
        "subscription": params.get("enabled") if subscription else params.get("disabled"),
        "status": params.get(client.status, ""),
    }
    if data.get("new_client"):
        page["status"] = params.get("waiting_for_text", "")
    return page


async def format_new_client_message(
    data: dict[str, Any], coach_lang: str, client_lang: str, preferable_type: str
) -> str:
    if data.get("new_client"):
        return msg_text("new_client", coach_lang).format(lang=client_lang, workout_type=preferable_type)
    else:
        service = service_types(coach_lang).get(data.get("service_type", ""), "")
        return msg_text("incoming_request", coach_lang).format(
            service=service, lang=client_lang, workout_type=preferable_type
        )


def get_workout_types(language: str) -> dict[str, str]:
    return workout_types(language)


def get_translated_week_day(lang_code: str, day: str | None) -> str:
    if day is None:
        return ""
    return days_of_week(lang_code).get(day, "")
