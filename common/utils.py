import re
from typing import Any, Optional

import aiohttp
import loguru
from aiogram.fsm.state import State

from bot.states import States
from common.models import Client, Coach
from common.user_service import user_service
from texts.text_manager import ButtonText, MessageText, translate

logger = loguru.logger


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
            "verified": verification_status.get(
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


def get_client_page(client: Client, lang_code: str, subscription: bool, payment_status: bool) -> dict[str, Any]:
    texts = {
        "male": translate(ButtonText.male, lang=lang_code),
        "female": translate(ButtonText.female, lang=lang_code),
        "enabled": translate(ButtonText.enabled, lang=lang_code),
        "disabled": translate(ButtonText.disabled, lang=lang_code),
        "waiting": translate(MessageText.waiting, lang=lang_code),
        "ok": translate(MessageText.program_compiled, lang=lang_code),
    }

    return {
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


async def short_url(url: str) -> str:
    if url.startswith("https://tinyurl.com/"):
        return url

    async with aiohttp.ClientSession() as session:
        params = {"url": url}
        async with session.get("http://tinyurl.com/api-create.php", params=params) as response:
            response_text = await response.text()
            if response.status == 200:
                return response_text
            else:
                logger.error(f"Failed to process URL: {response.status}, {response_text}")
                return url


async def format_message(data: dict[str, Any], coach_lang: str, client_lang: str, preferable_type: str) -> str:
    if data.get("new_client"):
        return translate(MessageText.new_client, coach_lang).format(lang=client_lang, workout_type=preferable_type)
    else:
        service_types = await get_service_types(coach_lang)
        service_type = data.get("request_type")
        service = service_types.get(service_type)
        return translate(MessageText.incoming_request, coach_lang).format(
            service=service, lang=client_lang, workout_type=preferable_type
        )


async def get_workout_types(language: str) -> dict:
    return {
        "home": translate(ButtonText.home_workout, language),
        "street": translate(ButtonText.street_workout, language),
        "gym": translate(ButtonText.gym_workout, language),
    }


async def get_service_types(language: str) -> dict:
    return {
        "subscription": translate(ButtonText.subscription, language),
        "program": translate(ButtonText.program, language),
    }
