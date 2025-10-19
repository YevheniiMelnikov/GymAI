from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, condecimal, field_validator

from core.encryptor import Encryptor
from core.enums import ClientStatus, CoachType, Gender, Language, PaymentStatus, ProfileRole

Price = condecimal(max_digits=10, decimal_places=2, gt=0)
NonNegativePrice = condecimal(max_digits=10, decimal_places=2, ge=0)


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
    credits: int = Field(default=500, ge=0)
    profile_data: dict[str, Any] = {}

    @field_validator("born_in", mode="before")
    @classmethod
    def born_in_to_str(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


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
    payout_due: NonNegativePrice | None = None
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
    split_number: int | None = None
    workout_type: str | None = None
    wishes: str | None = None
    coach_type: CoachType = CoachType.human
    model_config = ConfigDict(extra="ignore")

    @field_validator("client_profile", mode="before")
    @classmethod
    def _normalize_client_profile(cls, value: Any) -> int:
        if isinstance(value, dict):
            return int(value.get("id", 0))
        return int(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _normalize_created_at(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return datetime.fromisoformat(str(value)).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    @field_validator("split_number", mode="before")
    @classmethod
    def _set_split_number(cls, value: Any, info: Any) -> int:
        if value is None:
            data = getattr(info, "data", {}) or {}
            days: list[Any] = data.get("exercises_by_day", [])
            return len(days)
        return int(value)

    @field_validator("coach_type", mode="before")
    @classmethod
    def _normalize_coach_type(cls, value: Any) -> CoachType:
        if isinstance(value, dict):
            value = value.get("coach_type")
        if isinstance(value, str):
            try:
                return CoachType(value)
            except ValueError:
                return CoachType.human
        if isinstance(value, CoachType):
            return value
        return CoachType.human


class Subscription(BaseModel):
    id: int
    client_profile: int
    enabled: bool
    price: int
    workout_type: str
    wishes: str
    period: str
    workout_days: list[str] = Field(default_factory=list)
    exercises: list[DayExercises] = Field(default_factory=list)
    payment_date: str
    model_config = ConfigDict(extra="ignore")

    @field_validator("payment_date", mode="before")
    @classmethod
    def normalize_payment_date(cls, value: Any) -> str:
        try:
            return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return str(value)


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

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return datetime.fromisoformat(str(value)).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0


class QAResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
