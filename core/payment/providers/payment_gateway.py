from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Protocol


class CheckoutPayload(Protocol):
    @property
    def data(self) -> str: ...

    @property
    def signature(self) -> str: ...

    @property
    def checkout_url(self) -> str: ...


class PaymentGateway(ABC):
    """Abstract payments gateway interface."""

    @abstractmethod
    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> str:
        """Return URL to perform the payments."""
        ...

    @abstractmethod
    def build_checkout(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        profile_id: int,
    ) -> CheckoutPayload:
        """Return structured payload for embedded checkout."""
        ...
