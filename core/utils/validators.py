import re
from typing import Any, TypeVar
from pydantic import BaseModel, ValidationError
from loguru import logger

from config.app_settings import settings
from core.exceptions import UserServiceError

ModelT = TypeVar("ModelT", bound=BaseModel)
_YEAR_PATTERN = re.compile(r"(\d{4})")


def validate_or_raise(data: dict[str, Any], model_cls: type[ModelT], context: str = "") -> ModelT:
    try:
        validated: ModelT = model_cls.model_validate(data)
        return validated
    except ValidationError as e:
        name: str = str(getattr(model_cls, "__name__", None) or model_cls.__class__.__name__)
        context_text = f" in {context}" if context else ""
        msg = f"Validation failed for {name}{context_text}: {e}"
        logger.error(msg)
        raise UserServiceError(message=f"Invalid {name} data", code=500, details=msg)


def is_valid_year(text: str) -> bool:
    return text.isdigit() and settings.MIN_BIRTH_YEAR <= int(text) <= settings.MAX_BIRTH_YEAR


def extract_birth_year(text: str) -> int | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if is_valid_year(cleaned):
        return int(cleaned)
    candidates = [int(match) for match in _YEAR_PATTERN.findall(cleaned)]
    for year in reversed(candidates):
        if settings.MIN_BIRTH_YEAR <= year <= settings.MAX_BIRTH_YEAR:
            return year
    return None
