"""Validated payloads for AI coach Celery tasks."""

from pydantic import BaseModel, Field, field_validator

from core.enums import WorkoutPlanType, WorkoutType


class AiPlanBasePayload(BaseModel):
    client_id: int
    client_profile_id: int | None
    language: str
    plan_type: WorkoutPlanType
    wishes: str = ""
    request_id: str

    model_config = {"use_enum_values": True}

    @field_validator("client_id")
    @classmethod
    def _ensure_client_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("client_id must be positive")
        return value

    @field_validator("client_profile_id")
    @classmethod
    def _ensure_client_profile_id(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("client_profile_id must be positive")
        return value

    @field_validator("request_id")
    @classmethod
    def _ensure_request_id(cls, value: str) -> str:
        if not value:
            raise ValueError("request_id must be provided")
        return value


class AiPlanGenerationPayload(AiPlanBasePayload):
    workout_type: WorkoutType
    period: str | None = None
    workout_days: list[str] = Field(default_factory=list)


class AiPlanUpdatePayload(AiPlanBasePayload):
    expected_workout_result: str
    feedback: str
    workout_type: WorkoutType | None = None


class AiAttachmentPayload(BaseModel):
    mime: str
    data_base64: str


class AiQuestionPayload(BaseModel):
    client_id: int
    client_profile_id: int
    language: str
    prompt: str
    request_id: str
    attachments: list[AiAttachmentPayload] = Field(default_factory=list)

    model_config = {"use_enum_values": True}

    @field_validator("client_id", "client_profile_id")
    @classmethod
    def _ensure_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("identifiers must be positive")
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


__all__ = [
    "AiAttachmentPayload",
    "AiPlanBasePayload",
    "AiPlanGenerationPayload",
    "AiPlanUpdatePayload",
    "AiQuestionPayload",
]
