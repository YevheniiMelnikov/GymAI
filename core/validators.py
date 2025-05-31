from typing import TypeVar, Type, cast
from pydantic import BaseModel, ValidationError
from loguru import logger
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
