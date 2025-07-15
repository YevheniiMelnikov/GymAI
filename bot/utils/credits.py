from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from config.env_settings import settings


@dataclass(frozen=True)
class CreditPackage:
    name: str
    credits: int
    price: Decimal


@dataclass(frozen=True)
class AIService:
    name: str
    credits: int


def uah_to_credits(
    price_uah: Decimal,
    *,
    credit_rate_max_pack: Decimal | None = None,
    max_markup_pct_on_cheap: Decimal = Decimal("0.30"),
    cheap_price_threshold: Decimal = Decimal("1500"),
    apply_markup: bool = True,
) -> int:
    """Convert UAH amount to credits using adaptive markup logic."""

    if credit_rate_max_pack is None:
        credit_rate_max_pack = settings.CREDIT_RATE_MAX_PACK

    raw_credits = price_uah / credit_rate_max_pack

    if apply_markup:
        if price_uah <= cheap_price_threshold:
            credits = raw_credits * (1 + max_markup_pct_on_cheap)
        else:
            credits = raw_credits.quantize(Decimal("1."), rounding=ROUND_HALF_UP)
    else:
        credits = raw_credits

    return int(credits.to_integral_value(rounding=ROUND_HALF_UP))


def required_credits(amount: Decimal) -> int:
    """Return how many credits are needed to pay for a service."""
    return uah_to_credits(amount)


def available_packages() -> list[CreditPackage]:
    return [
        CreditPackage("max", settings.PACKAGE_MAX_CREDITS, settings.PACKAGE_MAX_PRICE),
        CreditPackage("optimum", settings.PACKAGE_OPTIMUM_CREDITS, settings.PACKAGE_OPTIMUM_PRICE),
        CreditPackage("start", settings.PACKAGE_START_CREDITS, settings.PACKAGE_START_PRICE),
    ]


def available_ai_services() -> list[AIService]:
    return [
        AIService("program", int(settings.AI_PROGRAM_PRICE)),
        AIService("subscription_14_days", int(settings.SMALL_AI_SUBSCRIPTION_PRICE)),
        AIService("subscription_1_month", int(settings.MEDIUM_AI_SUBSCRIPTION_PRICE)),
        AIService("subscription_6_months", int(settings.LARGE_AI_SUBSCRIPTION_PRICE)),
        AIService("ask_ai", int(settings.ASK_AI_PRICE)),
    ]
