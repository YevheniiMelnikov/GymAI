from enum import Enum


class ProfileRole(str, Enum):
    client = "client"
    coach = "coach"

    def __str__(self) -> str:
        return self.value


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


class CoachType(str, Enum):
    human = "human"
    ai_coach = "ai_coach"
    ai = ai_coach  # alias for backward compatibility

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


class CoachAgentMode(str, Enum):
    ASK_AI = "ask_ai"
    PROGRAM = "program"
    UPDATE = "update"
    SUBSCRIPTION = "subscription"
