from dataclasses import dataclass
from typing import Any


@dataclass
class Profile:
    id: int
    status: str
    language: str | None = None
    last_used: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        fields = ["id", "status", "language", "last_used"]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "language": self.language,
            "last_used": self.last_used,
        }

    def __repr__(self) -> str:
        return f"Profile(id={self.id}, status={self.status}, language={self.language}, last_used={self.last_used})"


@dataclass
class Client:
    id: int
    gender: str
    birth_date: str
    workout_experience: str
    workout_goals: str
    health_notes: str
    weight: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Client":
        fields = ["id", "gender", "birth_date", "workout_experience", "workout_goals", "health_notes", "weight"]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gender": self.gender,
            "birth_date": self.birth_date,
            "workout_experience": self.workout_experience,
            "workout_goals": self.workout_goals,
            "health_notes": self.health_notes,
            "weight": self.weight,
        }

    def __repr__(self) -> str:
        return (
            f"Client(id={self.id}, gender={self.gender}, birth_date={self.birth_date}, workout_experience={self.workout_experience}, "
            f"workout_goals={self.workout_goals}, health_notes={self.health_notes}, weight={self.weight})"
        )


@dataclass
class Coach:
    id: int
    name: str
    experience: int
    additional_info: str
    payment_details: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Coach":
        fields = ["id", "name", "experience", "additional_info", "payment_details"]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "experience": self.experience,
            "additional_info": self.additional_info,
            "payment_details": self.payment_details,
        }

    def __repr__(self) -> str:
        return (
            f"Coach(id={self.id}, name={self.name}, experience={self.experience}, additional_info={self.additional_info}, "
            f"payment_details={self.payment_details})"
        )
