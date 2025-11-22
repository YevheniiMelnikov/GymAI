from pydantic import BaseModel, Field, field_validator


class AiAnswerNotify(BaseModel):
    request_id: str
    status: str = "success"
    profile_id: int
    answer: str | None = None
    sources: list[str] = Field(default_factory=list)
    error: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return (value or "success").lower()
