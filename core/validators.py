from typing import TypeVar, Type, cast
# pydantic is optional during tests; provide a minimal stub if unavailable
try:  # pragma: no cover
    from pydantic import BaseModel, ValidationError
except Exception:  # pragma: no cover
    class ValidationError(Exception):
        pass

    class BaseModel:  # type: ignore[override]
        def __init__(self, **data):
            for k, v in data.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, data: dict):
            return cls(**data)
from loguru import logger

from config.app_settings import settings
from core.exceptions import UserServiceError

T = TypeVar("T", bound=BaseModel)


def validate_or_raise(data: dict, model_cls: Type[T], context: str = "") -> T:
    try:
        validated = model_cls.model_validate(data)
        return cast(T, validated)
    except ValidationError as e:
        msg = f"Validation failed for {model_cls.__name__}{' in ' + context if context else ''}: {e}"
        logger.error(msg)
        raise UserServiceError(message=f"Invalid {model_cls.__name__} data", code=500, details=msg)


def is_valid_year(text: str) -> bool:
    return text.isdigit() and settings.MIN_BIRTH_YEAR <= int(text) <= settings.MAX_BIRTH_YEAR
