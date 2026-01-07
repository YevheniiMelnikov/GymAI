from dataclasses import dataclass

from bot.types.credits import AIService, CreditPackage
from config.app_settings import settings
from core.enums import SubscriptionPeriod


@dataclass(frozen=True)
class ServiceCatalog:
    """Centralized pricing and service mapping for AI offerings."""

    @staticmethod
    def credit_packages() -> list[CreditPackage]:
        return [
            CreditPackage("max", settings.PACKAGE_MAX_CREDITS, settings.PACKAGE_MAX_PRICE),
            CreditPackage("optimum", settings.PACKAGE_OPTIMUM_CREDITS, settings.PACKAGE_OPTIMUM_PRICE),
            CreditPackage("start", settings.PACKAGE_START_CREDITS, settings.PACKAGE_START_PRICE),
        ]

    @staticmethod
    def ai_services() -> list[AIService]:
        return [
            AIService("program", int(settings.AI_PROGRAM_PRICE)),
            AIService("subscription_1_month", int(settings.SMALL_SUBSCRIPTION_PRICE)),
            AIService("subscription_6_months", int(settings.MEDIUM_SUBSCRIPTION_PRICE)),
            AIService("subscription_12_months", int(settings.LARGE_SUBSCRIPTION_PRICE)),
            AIService("ask_ai", int(settings.ASK_AI_PRICE)),
            AIService("diet_plan", int(settings.DIET_PLAN_PRICE)),
        ]

    @classmethod
    def subscription_services(cls) -> list[AIService]:
        return [service for service in cls.ai_services() if service.name.startswith("subscription_")]

    @classmethod
    def service_price(cls, name: str) -> int | None:
        return next((service.credits for service in cls.ai_services() if service.name == name), None)

    @staticmethod
    def subscription_period(name: str) -> SubscriptionPeriod | None:
        period_map = {
            "subscription_1_month": SubscriptionPeriod.one_month,
            "subscription_6_months": SubscriptionPeriod.six_months,
            "subscription_12_months": SubscriptionPeriod.twelve_months,
        }
        return period_map.get(name)
