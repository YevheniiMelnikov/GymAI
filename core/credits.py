from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from config.env_settings import settings


@dataclass(frozen=True)
class CreditPackage:
    name: str
    credits: int
    price: Decimal


def uah_to_credits(amount: Decimal, rate: Decimal) -> int:
    return int((amount / rate).quantize(Decimal("1"), ROUND_HALF_UP))


def credits_to_uah(credits: int, rate: Decimal) -> Decimal:
    return (Decimal(credits) * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def required_credits(amount: Decimal, rate: Decimal) -> int:
    return uah_to_credits(amount * Decimal("1.3"), rate)


def available_packages() -> list[CreditPackage]:
    return [
        CreditPackage("start", settings.PACKAGE_START_CREDITS, settings.PACKAGE_START_PRICE),
        CreditPackage("optimum", settings.PACKAGE_OPTIMUM_CREDITS, settings.PACKAGE_OPTIMUM_PRICE),
        CreditPackage("max", settings.PACKAGE_MAX_CREDITS, settings.PACKAGE_MAX_PRICE),
    ]
