from enum import Enum


class PaymentType(str, Enum):
    subscription = "subscription"
    program = "program"


class ProfileStatus(str, Enum):
    client = "client"
    coach = "coach"


class ClientStatus(str, Enum):
    waiting_for_text = "waiting_for_text"
    default = "default"


class Language(str, Enum):
    ua = "ua"
    ru = "ru"
    eng = "eng"


class Gender(str, Enum):
    male = "male"
    female = "female"
