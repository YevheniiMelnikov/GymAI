from datetime import datetime
from typing import Annotated, Any
from pydantic import BaseModel, Field, field_validator, condecimal, ConfigDict

from core.encryptor import Encryptor
from core.enums import (
    ProfileRole,
    ClientStatus,
    Language,
    Gender,
    PaymentStatus,
    CoachType,
)

Price = condecimal(max_digits=10, decimal_places=2, gt=0)


class Profile(BaseModel):
    id: int
    role: Annotated[ProfileRole, Field()]
    tg_id: int
    language: Annotated[Language, Field()]
    model_config = ConfigDict(extra="ignore")


class Client(BaseModel):
    id: int
    profile: int
    name: str | None = None
    gender: Gender | None = None
    born_in: str | None = None
    workout_experience: str | None = None
    workout_goals: str | None = None
    profile_photo: str | None = None
    health_notes: str | None = None
    weight: int | None = None
    status: ClientStatus = ClientStatus.initial
    assigned_to: list[int] = Field(default_factory=list)
    credits: int = Field(default=1000, ge=0)  # pyrefly: ignore [no-matching-overload]
    profile_data: dict[str, Any] = {}

    @field_validator("born_in", mode="before")
    def born_in_to_str(cls, v):
        if v is None:
            return v
        return str(v)


class Coach(BaseModel):
    id: int
    profile: int
    name: str | None = None
    surname: str | None = None
    work_experience: int | None = None
    additional_info: str | None = None
    payment_details: str | None = None
    profile_photo: str | None = None
    subscription_price: Price | None = None
    program_price: Price | None = None
    assigned_to: list[int] = Field(default_factory=list)
    verified: bool = False
    coach_type: CoachType = CoachType.human
    profile_data: dict[str, Any] = {}
    model_config = ConfigDict(extra="ignore")

    @property
    def payment_details_plain(self) -> str:
        if not self.payment_details:
            return ""
        return Encryptor.decrypt(self.payment_details) or ""


class Exercise(BaseModel):
    name: str
    sets: str
    reps: str
    gif_link: str | None = None
    weight: str | None = None
    set_id: int | None = None
    drop_set: bool = False
    model_config = ConfigDict(extra="ignore")


class DayExercises(BaseModel):
    day: str
    exercises: list[Exercise]
    model_config = ConfigDict(extra="ignore")


class Program(BaseModel):
    id: int
    client_profile: int
    exercises_by_day: list[DayExercises] = Field(default_factory=list)
    created_at: float
    split_number: int
    workout_type: str
    wishes: str
    model_config = ConfigDict(extra="ignore")


class Subscription(BaseModel):
    id: int
    client_profile: int
    enabled: bool
    price: int
    workout_type: str
    wishes: str
    workout_days: list[str] = Field(default_factory=list)
    exercises: list[DayExercises] = Field(default_factory=list)
    payment_date: str
    model_config = ConfigDict(extra="ignore")

    @field_validator("payment_date", mode="before")
    def normalize_payment_date(cls, v: str) -> str:
        try:
            return datetime.fromisoformat(v).strftime("%Y-%m-%d")
        except Exception:
            return v


class Payment(BaseModel):
    id: int
    client_profile: int
    payment_type: str
    order_id: str
    amount: Price
    status: PaymentStatus
    created_at: float
    updated_at: float
    processed: bool = False
    payout_handled: bool = False
    error: str | None = None
    model_config = ConfigDict(extra="ignore")
