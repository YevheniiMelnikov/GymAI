from functools import lru_cache

from bot.texts import ButtonText, translate
from config.app_settings import settings


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
