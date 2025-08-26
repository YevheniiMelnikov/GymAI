from typing import Any, TypeVar, cast
from pydantic import BaseModel, ValidationError
from loguru import logger

from config.app_settings import settings
from core.exceptions import UserServiceError

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_or_raise(data: dict[str, Any], model_cls: type[ModelT], context: str = "") -> ModelT:
    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        name = cast(str, getattr(model_cls, "__name__", model_cls.__class__.__name__))
        context_text = f" in {context}" if context else ""
        msg = f"Validation failed for {name}{context_text}: {e}"
        logger.error(msg)
        raise UserServiceError(message=f"Invalid {name} data", code=500, details=msg)


def is_valid_year(text: str) -> bool:
    return text.isdigit() and settings.MIN_BIRTH_YEAR <= int(text) <= settings.MAX_BIRTH_YEAR
