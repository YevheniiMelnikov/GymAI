from dataclasses import dataclass, field, MISSING
from typing import Any, Type, TypeVar

T = TypeVar("T", bound="BaseEntity")


@dataclass
class BaseEntity:
    @classmethod
    def from_dict(cls: Type[T], data: dict[str, Any]) -> T:
        init_data = {}
        for field_name, field_info in cls.__dataclass_fields__.items():
            if field_name in data:
                init_data[field_name] = data[field_name]
            else:
                if field_info.default_factory is not MISSING:
                    init_data[field_name] = field_info.default_factory()
                elif field_info.default is not MISSING:
                    init_data[field_name] = field_info.default
                else:
                    raise TypeError(f"Field '{field_name}' is required for {cls.__name__} but not provided.")
        return cls(**init_data)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values()}

    def __repr__(self) -> str:
        field_str = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.__dataclass_fields__)
        return f"{self.__class__.__name__}({field_str})"


@dataclass
class Profile(BaseEntity):
    id: int
    status: str
    tg_id: int | None = None
    language: str | None = None


@dataclass
class Client(BaseEntity):
    id: int
    name: str
    gender: str
    born_in: str
    workout_experience: str
    workout_goals: str
    health_notes: str
    weight: int
    status: str = "default"
    assigned_to: list[int] = field(default_factory=list)


@dataclass
class Coach(BaseEntity):
    id: int
    name: str
    surname: str
    work_experience: int
    additional_info: str
    payment_details: str
    profile_photo: str
    subscription_price: int
    program_price: int
    assigned_to: list[int] = field(default_factory=list)
    verified: bool = False


@dataclass
class Exercise(BaseEntity):
    name: str
    sets: str
    reps: str
    gif_link: str | None
    weight: str | None


@dataclass
class Program(BaseEntity):
    id: int
    exercises_by_day: dict[str, list[Exercise]]
    created_at: float
    profile: int
    split_number: int
    workout_type: str
    wishes: str


@dataclass
class Subscription(BaseEntity):
    id: int
    payment_date: str
    enabled: bool
    price: int
    client_profile: int
    workout_type: str
    wishes: str
    workout_days: list[str] = field(default_factory=list)
    exercises: dict[str, list[tuple[str, int]]] = field(default_factory=dict)  # TODO: REDUCE OVERCOMPLEXITY


@dataclass
class Payment(BaseEntity):
    id: int
    profile: int
    payment_type: str
    order_id: str
    amount: int
    status: str
    created_at: float
    updated_at: float
    handled: bool = False
    error: str | None = None
