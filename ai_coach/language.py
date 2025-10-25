from typing import Final


_LANGUAGE_NAME_MAP: Final[dict[str, str]] = {
    "uk": "Ukrainian",
    "ua": "Ukrainian",
    "ukr": "Ukrainian",
    "ua-ua": "Ukrainian",
    "uk-ua": "Ukrainian",
    "en": "English",
    "eng": "English",
    "en-us": "English",
    "ru": "Russian",
    "rus": "Russian",
    "ru-ru": "Russian",
}


def resolve_language_name(locale: str) -> str:
    normalized_locale: str = locale.strip().lower()
    mapped: str | None = _LANGUAGE_NAME_MAP.get(normalized_locale)
    if mapped:
        return mapped
    simplified: str = normalized_locale.replace("_", "-")
    mapped = _LANGUAGE_NAME_MAP.get(simplified)
    if mapped:
        return mapped
    return locale


__all__ = ["resolve_language_name"]
