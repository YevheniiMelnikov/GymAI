from enum import Enum


class ClientStatus(str, Enum):
    waiting_for_text = "waiting_for_text"
    default = "default"
    waiting_for_subscription = "waiting_for_subscription"
    waiting_for_program = "waiting_for_program"
    initial = "initial"

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
    help = "help"
    feedback = "feedback"
    offer = "offer"
    info = "info"

    def __str__(self) -> str:
        return self.value


class WorkoutPlanType(str, Enum):
    PROGRAM = "program"
    SUBSCRIPTION = "subscription"

    def __str__(self) -> str:
        return self.value


class WorkoutType(str, Enum):
    HOME = "home"
    GYM = "gym"
    STRENGTH = "strength"

    def __str__(self) -> str:
        return self.value


class SubscriptionPeriod(str, Enum):
    one_month = "1m"
    six_months = "6m"

    def __str__(self) -> str:
        return self.value
