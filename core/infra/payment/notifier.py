from typing import Protocol, cast

from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text

from config.app_settings import settings
from core.payment.types import PaymentNotifier


class _TaskInvoker(Protocol):
    def delay(self, *args: object, **kwargs: object) -> object: ...


class TaskPaymentNotifier(PaymentNotifier):
    def __init__(
        self,
        task: _TaskInvoker | None = None,
    ) -> None:
        task_impl = task if task is not None else cast(_TaskInvoker, send_payment_message)
        self._task = task_impl

    def success(self, client_id: int, language: str) -> None:
        message = msg_text("payment_success", language)
        self._task.delay(client_id, message)

    def failure(self, client_id: int, language: str) -> None:
        message = msg_text("payment_failure", language).format(
            mail=settings.EMAIL,
            tg=settings.TG_SUPPORT_CONTACT,
        )
        self._task.delay(client_id, message)
