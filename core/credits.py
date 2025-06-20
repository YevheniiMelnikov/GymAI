from decimal import Decimal, ROUND_HALF_UP
import json

from config.env_settings import settings


def uah_to_credits(amount: Decimal, rate: Decimal) -> int:
    return int((amount / rate).quantize(Decimal("1"), ROUND_HALF_UP))


def credits_to_uah(credits: int, rate: Decimal) -> Decimal:
    return (Decimal(credits) * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def required_credits(amount: Decimal, rate: Decimal) -> int:
    return uah_to_credits(amount * Decimal("1.3"), rate)


def get_credit_packages() -> dict:
    try:
        return json.loads(settings.CREDIT_PACKAGES)
    except Exception:
        return {}
