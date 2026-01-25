from enum import Enum


class ProfileStatus(str, Enum):
    created = "created"
    completed = "completed"
    deleted = "deleted"

    def __str__(self) -> str:
        return self.value


class Language(str, Enum):
    ua = "ua"
    ru = "ru"
    eng = "eng"

    def __str__(self) -> str:
        return self.value


class Gender(str, Enum):
    male = "male"
    female = "female"

    def __str__(self) -> str:
        return self.value


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CLOSED = "CLOSED"

    def __str__(self) -> str:
        return self.value


class CommandName(str, Enum):
    start = "start"
    menu = "menu"
    language = "language"
    info = "info"

    def __str__(self) -> str:
        return self.value


class WorkoutPlanType(str, Enum):
    PROGRAM = "program"
    SUBSCRIPTION = "subscription"

    def __str__(self) -> str:
        return self.value


class WorkoutLocation(str, Enum):
    HOME = "home"
    GYM = "gym"
    STRENGTH = "strength"

    def __str__(self) -> str:
        return self.value


class SubscriptionPeriod(str, Enum):
    one_month = "1m"
    six_months = "6m"
    twelve_months = "12m"

    def __str__(self) -> str:
        return self.value
