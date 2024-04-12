from dataclasses import dataclass


@dataclass
class Person:
    tg_user_id: int
    short_name: str
    password: str
    status: str
    gender: str = None
    birth_date: str = None
    language: str = None

    @classmethod
    def from_dict(cls, data: dict):
        fields = ["tg_user_id", "short_name", "password", "status", "gender", "birth_date", "language"]
        filtered_data = {key: data.get(key) for key in fields}
        return cls(**filtered_data)

    def __repr__(self):
        return (
            f"Person(tg_user_id={self.tg_user_id}, short_name={self.short_name}, "
            f"password={self.password}, status={self.status}, gender={self.gender}, "
            f"birth_date={self.birth_date}, language={self.language})"
        )
