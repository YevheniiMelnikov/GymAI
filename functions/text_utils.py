from typing import Any, Optional

from aiogram.fsm.state import State

from bot.states import States
from core.cache_manager import CacheManager
from core.models import Client, Coach, Exercise
from services.profile_service import ProfileService
from bot.texts.text_manager import msg_text, btn_text


def validate_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if not any(char.isdigit() for char in password):
        return False
    if not any(char.isalpha() for char in password):
        return False

    return True


def get_profile_attributes(status: str, user: Optional[Client | Coach], lang: str) -> dict[str, str]:
    def get_attr(attr_name: str) -> str:
        return getattr(user, attr_name, "") if user else ""

    genders = {
        "male": btn_text("male", lang),
        "female": btn_text("female", lang),
    }
    verification_status = {
        True: msg_text("verified", lang),
        False: msg_text("not_verified", lang),
    }

    if status == "client":
        attributes = {
            "name": get_attr("name"),
            "gender": genders.get(get_attr("gender"), ""),
            "born_in": get_attr("born_in"),
            "experience": get_attr("workout_experience"),
            "goals": get_attr("workout_goals"),
            "weight": get_attr("weight"),
            "notes": get_attr("health_notes"),
        }
    else:
        attributes = {
            "name": get_attr("name"),
            "experience": get_attr("work_experience"),
            "notes": get_attr("additional_info"),
            "payment_details": get_attr("payment_details"),
            "subscription_price": get_attr("subscription_price"),
            "program_price": get_attr("program_price"),
            "verif_status": verification_status.get(get_attr("verified"), msg_text("not_verified", lang)),
        }

    return attributes


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    return {
        "workout_experience": (States.workout_experience, msg_text("workout_experience", lang)),
        "workout_goals": (States.workout_goals, msg_text("workout_goals", lang)),
        "weight": (States.weight, msg_text("weight", lang)),
        "health_notes": (States.health_notes, msg_text("health_notes", lang)),
        "work_experience": (States.work_experience, msg_text("work_experience", lang)),
        "additional_info": (States.additional_info, msg_text("additional_info", lang)),
        "payment_details": (States.payment_details, msg_text("payment_details", lang)),
        "subscription_price": (
            States.subscription_price,
            msg_text("enter_subscription_price", lang),
        ),
        "program_price": (States.program_price, msg_text("enter_program_price", lang)),
        "photo": (States.profile_photo, msg_text("upload_photo", lang)),
    }.get(callback, (None, None))


async def get_client_page(client: Client, lang_code: str, subscription: bool, data: dict[str, Any]) -> dict[str, Any]:
    texts = {
        "male": btn_text("male", lang_code),
        "female": btn_text("female", lang_code),
        "enabled": btn_text("enabled", lang_code),
        "disabled": btn_text("disabled", lang_code),
        "waiting_for_subscription": msg_text("waiting_for_subscription", lang_code),
        "waiting_for_program": msg_text("waiting_for_program", lang_code),
        "default": msg_text("client_default_status", lang_code),
        "waiting_for_text": msg_text("waiting_for_text", lang_code),
    }

    client_data = await ProfileService.get_profile(client.id)
    page = {
        "name": client.name,
        "gender": texts.get(client.gender, ""),
        "born_in": client.born_in,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
        "health_notes": client.health_notes,
        "weight": client.weight,
        "language": CacheManager.get_profile_data(client_data.get("tg_id"), client.id, "language"),
        "subscription": texts.get("enabled") if subscription else texts.get("disabled"),
        "status": texts.get(client.status),
    }
    if data.get("new_client"):
        page["status"] = texts.get("waiting_for_text")
    return page


async def format_new_client_message(
    data: dict[str, Any], coach_lang: str, client_lang: str, preferable_type: str
) -> str:
    if data.get("new_client"):
        return msg_text("new_client", coach_lang).format(lang=client_lang, workout_type=preferable_type)
    else:
        service_types = await get_service_types(coach_lang)
        service_type = data.get("request_type")
        service = service_types.get(service_type)
        return msg_text("incoming_request", coach_lang).format(
            service=service, lang=client_lang, workout_type=preferable_type
        )


async def get_service_types(language: str) -> dict:
    return {
        "subscription": btn_text("subscription", language),
        "program": btn_text("program", language),
    }


async def get_workout_types(language: str) -> dict:
    return {
        "home": btn_text("home_workout", language),
        "street": btn_text("street_workout", language),
        "gym": btn_text("gym_workout", language),
    }


def get_translated_week_day(lang_code: str, day: str) -> str:
    days = {
        "monday": btn_text("monday", lang_code),
        "tuesday": btn_text("tuesday", lang_code),
        "wednesday": btn_text("wednesday", lang_code),
        "thursday": btn_text("thursday", lang_code),
        "friday": btn_text("friday", lang_code),
        "saturday": btn_text("saturday", lang_code),
        "sunday": btn_text("sunday", lang_code),
    }
    return days.get(day)


async def format_program(exercises: dict[str, Any], day: int) -> str:
    program_lines = []
    exercises_data = exercises.get(str(day), [])
    exercises = [Exercise(**e) if isinstance(e, dict) else e for e in exercises_data]

    for idx, exercise in enumerate(exercises):
        line = f"{idx + 1}. {exercise.name} | {exercise.sets} x {exercise.reps}"
        if exercise.weight:
            line += f" | {exercise.weight} kg"
        if exercise.gif_link:
            line += f" | <a href='{exercise.gif_link}'>GIF</a>"
        program_lines.append(line)

    return "\n".join(program_lines)
