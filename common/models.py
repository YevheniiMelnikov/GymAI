from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

T = TypeVar("T", bound="BaseEntity")


@dataclass
class BaseEntity:
    id: int

    @classmethod
    def from_dict(cls: Type[T], data: dict[str, Any]) -> T:
        fields = {field.name for field in cls.__dataclass_fields__.values()}
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values()}

    def __repr__(self) -> str:
        field_str = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.__dataclass_fields__)
        return f"{self.__class__.__name__}({field_str})"


@dataclass
class Profile(BaseEntity):
    status: str
    language: str | None = None
    last_used: float | None = None


@dataclass
class Client(BaseEntity):
    name: str
    gender: str
    birth_date: str
    workout_experience: str
    workout_goals: str
    health_notes: str
    weight: int
    tg_id: int
    assigned_to: list[int] = field(default_factory=list)


@dataclass
class Coach(BaseEntity):
    name: str
    work_experience: int
    additional_info: str
    payment_details: str
    profile_photo: str
    tg_id: int
    assigned_to: list[int] = field(default_factory=list)
    verified: bool = False


@dataclass
class Program(BaseEntity):
    profile_id: int
    exercises: list[str]
    created_at: float
    profile: int


@dataclass
class Subscription(BaseEntity):
    payment_date: float
    enabled: bool
    price: float
    profile: int
