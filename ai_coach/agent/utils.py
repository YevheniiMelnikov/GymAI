from typing import Final

from ai_coach.agent.knowledge.context import current_kb, get_or_create_kb
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.schemas import ProgramPayload
from core.enums import CoachType
from core.schemas import Program


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


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        coach_type = getattr(payload, "_coach_type_raw", data.get("coach_type"))
        if isinstance(coach_type, str):
            normalized = coach_type.lower()
            mapping = {
                "ai": CoachType.ai_coach,
                "ai_coach": CoachType.ai_coach,
                "human": CoachType.human,
            }
            data["coach_type"] = mapping.get(normalized, CoachType.ai_coach)
        if data.get("split_number") is None:
            data["split_number"] = len(getattr(payload, "exercises_by_day", []))
        return Program.model_validate(data)


def get_knowledge_base() -> KnowledgeBase:
    existing = current_kb()
    if existing is not None:
        return existing
    return get_or_create_kb()


__all__ = ["resolve_language_name", "ProgramAdapter", "get_knowledge_base"]
