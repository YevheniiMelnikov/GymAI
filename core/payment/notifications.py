from typing import Protocol

from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from config.app_settings import settings


class PaymentNotifier(Protocol):
    def success(self, client_id: int, language: str) -> None: ...

    def failure(self, client_id: int, language: str) -> None: ...


class TaskPaymentNotifier:
    @staticmethod
    def success(client_id: int, language: str) -> None:
        send_payment_message.delay(  # pyrefly: ignore[not-callable]
            client_id, msg_text("payment_success", language)
        )

    @staticmethod
    def failure(client_id: int, language: str) -> None:
        send_payment_message.delay(  # pyrefly: ignore[not-callable]
            client_id,
            msg_text("payment_failure", language).format(
                mail=settings.EMAIL,
                tg=settings.TG_SUPPORT_CONTACT,
            ),
        )
