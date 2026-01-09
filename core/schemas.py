from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, condecimal, field_validator, model_validator

from config.app_settings import settings
from core.enums import ProfileStatus, Gender, Language, PaymentStatus

Price = condecimal(max_digits=10, decimal_places=2, gt=0)
NonNegativePrice = condecimal(max_digits=10, decimal_places=2, ge=0)


class Profile(BaseModel):
    id: int
    tg_id: int
    language: Annotated[Language, Field()]
    status: ProfileStatus = ProfileStatus.created
    gift_credits_granted: bool = False
    deleted_at: datetime | None = None
    gender: Gender | None = None
    born_in: str | None = None
    workout_experience: str | None = None
    workout_goals: str | None = None
    health_notes: str | None = None
    weight: int | None = None
    height: int | None = None
    workout_location: str | None = None
    diet_allergies: str | None = None
    diet_products: list[str] | None = None
    credits: int = Field(default=settings.DEFAULT_CREDITS, ge=0)
    profile_data: dict[str, Any] = {}
    model_config = ConfigDict(extra="ignore")

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> str:
        if isinstance(value, str) and value.lower() == "en":
            return "eng"
        if hasattr(value, "value"):
            return value.value
        return value

    @field_validator("born_in", mode="before")
    @classmethod
    def born_in_to_str(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class ExerciseSetDetail(BaseModel):
    reps: int
    weight: float
    weight_unit: str | None = None
    model_config = ConfigDict(extra="ignore")


class Exercise(BaseModel):
    name: str
    sets: str | int
    reps: str | int
    weight: str | None = None
    set_id: int | None = None
    gif_key: str | None = None
    drop_set: bool = False
    superset_id: int | None = None
    superset_order: int | None = None
    sets_detail: list[ExerciseSetDetail] | None = None
    model_config = ConfigDict(extra="ignore")


class DayExercises(BaseModel):
    day: str
    exercises: list[Exercise]
    model_config = ConfigDict(extra="ignore")


class Program(BaseModel):
    id: int
    profile: int
    exercises_by_day: list[DayExercises] = Field(default_factory=list)
    created_at: float
    split_number: int | None = None
    workout_location: str | None = None
    wishes: str | None = None
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    @field_validator("profile", mode="before")
    @classmethod
    def _normalize_profile(cls, value: Any) -> int:
        if isinstance(value, dict):
            return int(value.get("id", 0))
        if hasattr(value, "id"):
            return int(value.id)
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

    @model_validator(mode="after")
    def _set_split_number(self) -> "Program":
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day) or 1
        return self


class Subscription(BaseModel):
    id: int
    profile: int
    enabled: bool
    price: int
    workout_location: str
    wishes: str
    period: str
    split_number: int = Field(ge=1, le=7)
    exercises: list[DayExercises] = Field(default_factory=list)
    payment_date: str | None = None
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _fill_split_number(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        split_raw = values.get("split_number")
        if split_raw in (None, ""):
            fallback = 0
            workout_days = values.get("workout_days")
            if isinstance(workout_days, list):
                fallback = len(workout_days)
            if not fallback:
                exercises = values.get("exercises")
                if isinstance(exercises, list):
                    fallback = len(exercises)
            if not fallback:
                fallback = 3
            values["split_number"] = max(1, min(7, int(fallback)))
        return values

    @field_validator("profile", mode="before")
    @classmethod
    def _normalize_profile(cls, value: Any) -> int:
        if isinstance(value, dict):
            return int(value.get("id", 0))
        if hasattr(value, "id"):
            return int(value.id)
        return int(value)

    @field_validator("payment_date", mode="before")
    @classmethod
    def normalize_payment_date(cls, value: Any) -> str | None:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return str(value)


class Payment(BaseModel):
    id: int
    profile: int
    payment_type: str
    order_id: str
    amount: Price
    status: PaymentStatus
    created_at: float
    updated_at: float
    processed: bool = False
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


class QAResponseBlock(BaseModel):
    title: str | None = None
    body: str


class QAResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    blocks: list[QAResponseBlock] | None = None


class NutritionTotals(BaseModel):
    calories: int
    protein_g: float
    fat_g: float
    carbs_g: float
    model_config = ConfigDict(extra="ignore")


class DietPlanItem(BaseModel):
    name: str
    grams: int
    calories: int
    protein_g: float
    fat_g: float
    carbs_g: float
    model_config = ConfigDict(extra="ignore")


class DietMeal(BaseModel):
    name: str
    items: list[DietPlanItem] = Field(default_factory=list)
    totals: NutritionTotals
    model_config = ConfigDict(extra="ignore")


class DietPlan(BaseModel):
    id: int | None = None
    meals: list[DietMeal] = Field(default_factory=list)
    totals: NutritionTotals
    notes: list[str] = Field(default_factory=list)
    schema_version: str | None = None
    model_config = ConfigDict(extra="ignore")
