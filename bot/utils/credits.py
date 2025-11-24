from dataclasses import dataclass
from decimal import Decimal

from config.app_settings import settings


@dataclass(frozen=True)
class CreditPackage:
    name: str
    credits: int
    price: Decimal


@dataclass(frozen=True)
class AIService:
    name: str
    credits: int


def available_packages() -> list[CreditPackage]:
    return [
        CreditPackage("max", settings.PACKAGE_MAX_CREDITS, settings.PACKAGE_MAX_PRICE),
        CreditPackage("optimum", settings.PACKAGE_OPTIMUM_CREDITS, settings.PACKAGE_OPTIMUM_PRICE),
        CreditPackage("start", settings.PACKAGE_START_CREDITS, settings.PACKAGE_START_PRICE),
    ]


def available_ai_services() -> list[AIService]:
    return [
        AIService("program", int(settings.AI_PROGRAM_PRICE)),
        AIService("subscription_1_month", int(settings.REGULAR_AI_SUBSCRIPTION_PRICE)),
        AIService("subscription_6_months", int(settings.LARGE_AI_SUBSCRIPTION_PRICE)),
        AIService("ask_ai", int(settings.ASK_AI_PRICE)),
    ]
