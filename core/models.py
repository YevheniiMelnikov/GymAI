from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, Field, field_validator, condecimal
from enums import PaymentType, ProfileStatus, ClientStatus, Language, Gender


Price = condecimal(max_digits=10, decimal_places=2, gt=0)


class Profile(BaseModel):
    id: int
    status: Annotated[ProfileStatus, Field()]
    tg_id: int
    language: Annotated[Language, Field()]


class Client(BaseModel):
    id: int
    profile: int
    name: str
    gender: Gender
    born_in: str
    workout_experience: str
    workout_goals: str
    health_notes: str
    weight: int
    status: ClientStatus = ClientStatus.default
    assigned_to: list[int] = Field(default_factory=list)


class Coach(BaseModel):
    id: int
    profile: int
    name: str
    surname: str
    work_experience: int
    additional_info: str
    payment_details: str
    profile_photo: str
    subscription_price: Price
    program_price: Price
    assigned_to: list[int] = Field(default_factory=list)
    verified: bool = False


class Exercise(BaseModel):
    name: str
    sets: str
    reps: str
    gif_link: str | None = None
    weight: str | None = None


class DayExercises(BaseModel):
    day: str
    exercises: list[Exercise]


class Program(BaseModel):
    id: int
    exercises_by_day: list[DayExercises] = Field(default_factory=list)
    created_at: float
    profile: int
    split_number: int
    workout_type: str
    wishes: str


class Subscription(BaseModel):
    id: int
    payment_date: str
    enabled: bool
    price: int
    client_profile: int
    workout_type: str
    wishes: str
    workout_days: list[str] = Field(default_factory=list)
    exercises: list[DayExercises] = Field(default_factory=list)

    @field_validator("payment_date", mode="before")
    def normalize_payment_date(cls, v: str) -> str:
        try:
            return datetime.fromisoformat(v).strftime("%Y-%m-%d")
        except Exception:
            return v


class Payment(BaseModel):
    id: int
    profile: int
    payment_type: PaymentType
    order_id: str
    amount: Price
    status: str
    created_at: float
    updated_at: float
    handled: bool = False
    error: str | None = None
