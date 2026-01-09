from pydantic import BaseModel, Field, field_validator

from core.schemas import DietPlan, QAResponseBlock


class AiAnswerNotify(BaseModel):
    request_id: str
    status: str = "success"
    profile_id: int
    answer: str | None = None
    sources: list[str] = Field(default_factory=list)
    blocks: list[QAResponseBlock] = Field(default_factory=list)
    error: str | None = None
    force: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return (value or "success").lower()


class AiDietNotify(BaseModel):
    request_id: str
    status: str = "success"
    profile_id: int
    plan: DietPlan | None = None
    error: str | None = None
    force: bool = False
    cost: int | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return (value or "success").lower()


class WeeklySurveyRecipient(BaseModel):
    profile_id: int
    tg_id: int
    language: str | None = None
    subscription_id: int


class WeeklySurveyNotify(BaseModel):
    recipients: list[WeeklySurveyRecipient] = Field(default_factory=list)


class SubscriptionRenewalRecipient(BaseModel):
    profile_id: int
    tg_id: int
    language: str | None = None
    subscription_id: int


class SubscriptionRenewalNotify(BaseModel):
    recipients: list[SubscriptionRenewalRecipient] = Field(default_factory=list)
