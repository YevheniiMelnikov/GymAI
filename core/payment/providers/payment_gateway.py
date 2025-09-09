from abc import ABC, abstractmethod
from decimal import Decimal


class PaymentGateway(ABC):
    """Abstract payments gateway interface."""

    @abstractmethod
    async def get_payment_link(
        self,
        action: str,
        amount: Decimal,
        order_id: str,
        payment_type: str,
        client_id: int,
    ) -> str:
        """Return URL to perform the payments."""
        ...
