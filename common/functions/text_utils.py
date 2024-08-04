import re
from typing import Any, Optional

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State

from bot.states import States
from common.models import Client, Coach, Exercise
from common.user_service import user_service
from texts.text_manager import ButtonText, MessageText, translate


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
    def get_attr(attr_name):
        return getattr(user, attr_name, "") if user else ""

    genders = {
        "male": translate(ButtonText.male, lang=lang_code),
        "female": translate(ButtonText.female, lang=lang_code),
    }
    verification_status = {
        True: translate(MessageText.verified, lang=lang_code),
        False: translate(MessageText.not_verified, lang=lang_code),
    }

    if role == "client":
        attributes = {
            "name": get_attr("name"),
            "gender": genders.get(get_attr("gender"), ""),
            "birth_date": get_attr("birth_date"),
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
            "verif_status": verification_status.get(
                get_attr("verified"), translate(MessageText.not_verified, lang=lang_code)
            ),
        }

    return attributes


def get_state_and_message(callback: str, lang: str) -> tuple[State, str]:
    return {
        "workout_experience": (States.workout_experience, translate(MessageText.workout_experience, lang=lang)),
        "workout_goals": (States.workout_goals, translate(MessageText.workout_goals, lang=lang)),
        "weight": (States.weight, translate(MessageText.weight, lang=lang)),
        "health_notes": (States.health_notes, translate(MessageText.health_notes, lang=lang)),
        "work_experience": (States.work_experience, translate(MessageText.work_experience, lang=lang)),
        "additional_info": (States.additional_info, translate(MessageText.additional_info, lang=lang)),
        "payment_details": (States.payment_details, translate(MessageText.payment_details, lang=lang)),
        "photo": (States.profile_photo, translate(MessageText.upload_photo, lang=lang)),
    }.get(callback, (None, None))


def get_coach_page(coach: Coach) -> dict[str, Any]:
    return {"name": coach.name, "experience": coach.work_experience, "additional_info": coach.additional_info}


async def get_client_page(
    client: Client, lang_code: str, subscription: bool, payment_status: bool, state: FSMContext
) -> dict[str, Any]:
    texts = {
        "male": translate(ButtonText.male, lang=lang_code),
        "female": translate(ButtonText.female, lang=lang_code),
        "enabled": translate(ButtonText.enabled, lang=lang_code),
        "disabled": translate(ButtonText.disabled, lang=lang_code),
        "waiting": translate(MessageText.waiting, lang=lang_code),
        "ok": translate(MessageText.program_compiled, lang=lang_code),
        "waiting_for_text": translate(MessageText.waiting_for_text, lang=lang_code),
    }

    page = {
        "name": client.name,
        "gender": texts.get(client.gender, ""),
        "birth_date": client.birth_date,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
        "health_notes": client.health_notes,
        "weight": client.weight,
        "language": user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language"),
        "subscription": texts.get("enabled") if subscription else texts.get("disabled"),
        "status": texts.get("waiting") if payment_status else texts.get("ok"),
    }
    data = await state.get_data()
    if data.get("new_client"):
        page["status"] = texts.get("waiting_for_text")
    return page


async def format_new_client_message(
    data: dict[str, Any], coach_lang: str, client_lang: str, preferable_type: str
) -> str:
    if data.get("new_client"):
        return translate(MessageText.new_client, coach_lang).format(lang=client_lang, workout_type=preferable_type)
    else:
        service_types = await get_service_types(coach_lang)
        service_type = data.get("request_type")
        service = service_types.get(service_type)
        return translate(MessageText.incoming_request, coach_lang).format(
            service=service, lang=client_lang, workout_type=preferable_type
        )


async def get_service_types(language: str) -> dict:
    return {
        "subscription": translate(ButtonText.subscription, language),
        "program": translate(ButtonText.program, language),
    }


async def get_workout_types(language: str) -> dict:
    return {
        "home": translate(ButtonText.home_workout, language),
        "street": translate(ButtonText.street_workout, language),
        "gym": translate(ButtonText.gym_workout, language),
    }


def get_translated_week_day(lang_code: str, day: str) -> str:
    days = {
        "monday": translate(ButtonText.monday, lang_code),
        "tuesday": translate(ButtonText.tuesday, lang_code),
        "wednesday": translate(ButtonText.wednesday, lang_code),
        "thursday": translate(ButtonText.thursday, lang_code),
        "friday": translate(ButtonText.friday, lang_code),
        "saturday": translate(ButtonText.saturday, lang_code),
        "sunday": translate(ButtonText.sunday, lang_code),
    }
    return days.get(day)


async def format_program(exercises: dict[str, any], day: int) -> str:
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
