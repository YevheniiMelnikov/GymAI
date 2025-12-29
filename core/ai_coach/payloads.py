from pydantic import BaseModel, Field, field_validator

from core.enums import WorkoutPlanType, WorkoutLocation


class AiPlanBasePayload(BaseModel):
    profile_id: int
    language: str
    plan_type: WorkoutPlanType
    wishes: str = ""
    request_id: str

    model_config = {"use_enum_values": True}

    @field_validator("profile_id")
    @classmethod
    def _ensure_profile_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("profile_id must be positive")
        return value

    @field_validator("request_id")
    @classmethod
    def _ensure_request_id(cls, value: str) -> str:
        if not value:
            raise ValueError("request_id must be provided")
        return value


class AiPlanGenerationPayload(AiPlanBasePayload):
    workout_location: WorkoutLocation
    period: str | None = None
    split_number: int
    previous_subscription_id: int | None = None

    @field_validator("split_number")
    @classmethod
    def _ensure_split_number(cls, value: int) -> int:
        if value < 1 or value > 7:
            raise ValueError("split_number must be between 1 and 7")
        return value


class AiPlanUpdatePayload(AiPlanBasePayload):
    feedback: str
    workout_location: WorkoutLocation | None = None


class AiAttachmentPayload(BaseModel):
    mime: str
    data_base64: str


class AiQuestionPayload(BaseModel):
    profile_id: int
    language: str
    prompt: str
    request_id: str
    cost: int
    attachments: list[AiAttachmentPayload] = Field(default_factory=list)

    model_config = {"use_enum_values": True}

    @field_validator("profile_id")
    @classmethod
    def _ensure_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("profile_id must be positive")
        return value

    @field_validator("prompt")
    @classmethod
    def _ensure_prompt(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("prompt must not be empty")
        return value

    @field_validator("request_id")
    @classmethod
    def _ensure_request_id(cls, value: str) -> str:
        if not value:
            raise ValueError("request_id is required")
        return value


class AiDietPlanPayload(BaseModel):
    profile_id: int
    language: str
    request_id: str
    cost: int
    prompt: str
    diet_allergies: str | None = None
    diet_products: list[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}

    @field_validator("profile_id")
    @classmethod
    def _ensure_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("profile_id must be positive")
        return value

    @field_validator("request_id")
    @classmethod
    def _ensure_diet_request_id(cls, value: str) -> str:
        if not value:
            raise ValueError("request_id is required")
        return value

    @field_validator("prompt")
    @classmethod
    def _ensure_prompt(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("prompt must not be empty")
        return value

    @field_validator("cost")
    @classmethod
    def _ensure_cost(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("cost must be positive")
        return value
