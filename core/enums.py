from enum import Enum


class PaymentType(str, Enum):
    subscription = "subscription"
    program = "program"
    credits = "credits"


class ProfileRole(str, Enum):
    client = "client"
    coach = "coach"


class ClientStatus(str, Enum):
    waiting_for_text = "waiting_for_text"
    default = "default"
    waiting_for_subscription = "waiting_for_subscription"
    waiting_for_program = "waiting_for_program"
    initial = "initial"


class Language(str, Enum):
    ua = "ua"
    ru = "ru"
    eng = "eng"


class Gender(str, Enum):
    male = "male"
    female = "female"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CLOSED = "CLOSED"
