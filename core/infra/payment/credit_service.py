from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable, Protocol

from bot.utils.credits import available_packages, uah_to_credits

from core.payment.types import CreditService


class _CreditPackage(Protocol):
    price: Decimal
    credits: int


CreditConverter = Callable[[Decimal], int]
PackageProvider = Callable[[], Iterable[_CreditPackage]]


class BotCreditService(CreditService):
    def __init__(
        self,
        packages_provider: PackageProvider | None = None,
        converter: CreditConverter | None = None,
    ) -> None:
        self._packages_provider: PackageProvider = packages_provider or available_packages
        if converter is None:

            def _convert(value: Decimal) -> int:
                return uah_to_credits(value, apply_markup=False)

            self._converter: CreditConverter = _convert
        else:
            self._converter = converter

    def credits_for_amount(self, amount: Decimal) -> int:
        normalized_amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        package_map = {package.price: package.credits for package in self._packages_provider()}
        credits = package_map.get(normalized_amount)
        if credits is not None:
            return credits
        return self._converter(normalized_amount)
