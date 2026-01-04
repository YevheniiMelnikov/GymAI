from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from core.enums import SubscriptionPeriod

if TYPE_CHECKING:
    from django.http import JsonResponse
    from apps.profiles.models import Profile


@dataclass(frozen=True)
class AuthResult:
    profile: "Profile | None"
    error: "JsonResponse | None"


@dataclass(frozen=True)
class CreditPackageInfo:
    package_id: str
    credits: int
    price: Decimal


@dataclass(frozen=True)
class SubscriptionPlanOption:
    period: SubscriptionPeriod
    months: int
    price: int


@dataclass(frozen=True)
class WorkoutPlanPricing:
    program_price: int
    subscriptions: tuple[SubscriptionPlanOption, ...]
