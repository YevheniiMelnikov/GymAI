from dataclasses import dataclass


@dataclass
class Profile:
    id: int
    status: str
    gender: str = None
    birth_date: str = None
    language: str = None

    @classmethod
    def from_dict(cls, data: dict):
        fields = ["id", "status", "gender", "birth_date", "language"]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def __repr__(self):
        return (
            f"Profile(id={self.id}, status={self.status}, gender={self.gender}, "
            f"birth_date={self.birth_date}, language={self.language})"
        )
