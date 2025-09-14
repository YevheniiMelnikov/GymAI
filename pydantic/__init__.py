from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, TypeVar

T = TypeVar("T")


class ValidationError(Exception):
    pass


class BaseModel:
    def __init__(self, **data: Any) -> None:
        for k, v in data.items():
            setattr(self, k, v)

    def model_dump(self, *, exclude_none: bool = False, exclude: set[str] | None = None, **_: Any) -> Dict[str, Any]:
        data = self.__dict__.copy()
        if exclude:
            for key in exclude:
                data.pop(key, None)
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data

    @classmethod
    def model_validate(cls, data: Dict[str, Any]) -> "BaseModel":
        return cls(**data)


def Field(default: Any | None = None, **_: Any) -> Any:
    return default


def condecimal(*_: Any, **__: Any) -> type[Decimal]:
    return Decimal


class ConfigDict(dict):
    pass


def field_validator(*args: Any, **kwargs: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return func

    return decorator


def model_validator(*args: Any, **kwargs: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return func

    return decorator
