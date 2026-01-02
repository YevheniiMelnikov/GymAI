from functools import lru_cache
from typing import Optional

from aiogram.fsm.state import State

from bot.states import States
from core.schemas import Profile
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


def get_profile_attributes(user: Optional[Profile], lang: str) -> dict[str, str]:
    def attr(name: str) -> str:
        val = getattr(user, name, "") if user else ""
        return str(val) if val is not None else ""

    def fill_template(template: str, **values: str) -> str:
        result = template
        for key, value in values.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def diet_block() -> str:
        if user is None:
            return ""
        allergies = str(user.diet_allergies or "").strip()
        products = user.diet_products or []
        if not allergies and not products:
            return ""
        separator = translate(MessageText.diet_preferences_separator, lang)
        title_line = translate(MessageText.diet_preferences_title_line, lang)
        allergies_line = translate(MessageText.diet_preferences_allergies_line, lang)
        products_header = translate(MessageText.diet_preferences_products_header, lang)
        product_item = translate(MessageText.diet_preferences_product_item, lang)
        lines = [title_line]
        if allergies:
            lines.append(fill_template(allergies_line, allergies=allergies))
        if products:
            product_labels = {
                "plant_food": translate(ButtonText.plant_food, lang),
                "meat": translate(ButtonText.meat, lang),
                "fish_seafood": translate(ButtonText.fish_seafood, lang),
                "eggs": translate(ButtonText.eggs, lang),
                "dairy": translate(ButtonText.dairy, lang),
            }
            translated = [product_labels.get(item, item) for item in products if str(item).strip()]
            if translated:
                lines.append(products_header)
                lines.extend(fill_template(product_item, product=product) for product in translated)
        return f"{separator}{'\n'.join(lines)}"

    location_key = attr("workout_location").strip().lower()
    workout_locations = get_workout_locations(lang)
    experience_key = attr("workout_experience").strip().lower()
    experience_levels = get_workout_experience_levels(lang)
    return {
        "born_in": attr("born_in"),
        "experience": experience_levels.get(experience_key, attr("workout_experience")),
        "goals": attr("workout_goals"),
        "workout_location": workout_locations.get(location_key, "") if location_key else "",
        "weight": attr("weight"),
        "height": attr("height"),
        "notes": attr("health_notes"),
        "diet_preferences": diet_block(),
    }


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
