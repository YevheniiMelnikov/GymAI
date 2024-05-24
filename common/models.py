from dataclasses import dataclass, field
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
    name: str
    gender: str
    birth_date: str
    workout_experience: str
    workout_goals: str
    health_notes: str
    weight: int
    tg_id: int
    assigned_to: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Client":
        fields = [
            "id",
            "name",
            "gender",
            "birth_date",
            "workout_experience",
            "workout_goals",
            "health_notes",
            "weight",
            "assigned_to",
            "tg_id",
        ]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "birth_date": self.birth_date,
            "workout_experience": self.workout_experience,
            "workout_goals": self.workout_goals,
            "health_notes": self.health_notes,
            "weight": self.weight,
            "assigned_to": self.assigned_to,
            "tg_id": self.tg_id,
        }

    def __repr__(self) -> str:
        return (
            f"Client(id={self.id}, name={self.name}, gender={self.gender}, birth_date={self.birth_date}, "
            f"workout_experience={self.workout_experience}, workout_goals={self.workout_goals}, "
            f"health_notes={self.health_notes}, weight={self.weight}), assigned_to={self.assigned_to}, "
            f"tg_id={self.tg_id}"
        )


@dataclass
class Coach:
    id: int
    name: str
    work_experience: int
    additional_info: str
    payment_details: str
    profile_photo: str
    tg_id: int
    assigned_to: list = field(default_factory=list)
    verified: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Coach":
        fields = [
            "id",
            "name",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "verified",
            "assigned_to",
            "tg_id",
        ]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "work_experience": self.work_experience,
            "additional_info": self.additional_info,
            "payment_details": self.payment_details,
            "profile_photo": self.profile_photo,
            "verified": self.verified,
            "assigned_to": self.assigned_to,
            "tg_id": self.tg_id,
        }

    def __repr__(self) -> str:
        return (
            f"Coach(id={self.id}, name={self.name}, work_experience={self.work_experience}, "
            f"additional_info={self.additional_info}, payment_details={self.payment_details}, "
            f"profile_photo={self.profile_photo}), verified={self.verified}), "
            f"assigned_to={self.assigned_to}, tg_id={self.tg_id}"
        )


@dataclass
class Subscription:
    expire_date: float
    enabled: bool
    price: float
    type: str


@dataclass
class Program:
    profile_id: int
    exercises: list[str]
    created_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Program":
        fields = [
            "profile_id",
            "exercises",
            "created_at",
        ]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "exercises": self.exercises,
            "created_at": self.created_at,
        }

    def __repr__(self) -> str:
        return f"Program(profile_id={self.profile_id}, exercises={self.exercises}, created_at={self.created_at})"
