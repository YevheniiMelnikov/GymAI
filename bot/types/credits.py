from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CreditPackage:
    """Credit package descriptor with price and credit amount."""

    name: str
    credits: int
    price: Decimal


@dataclass(frozen=True)
class AIService:
    """AI service descriptor with required credit amount."""

    name: str
    credits: int
