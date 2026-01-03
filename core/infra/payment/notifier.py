from typing import Protocol, cast
from collections import deque

from apps.payments.tasks import send_payment_message
from bot.texts import MessageText, translate

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
        self._undelivered = deque()

    def success(self, profile_id: int, language: str, credits: int) -> None:
        message = translate(MessageText.payment_success, language).format(credits=credits)
        self._task.delay(profile_id, message)
        self._undelivered.append(profile_id)

    def failure(self, profile_id: int, language: str) -> None:
        message = translate(MessageText.payment_failure, language).format(
            mail=settings.EMAIL,
            tg=settings.TG_SUPPORT_CONTACT,
        )
        self._task.delay(profile_id, message)
        self._undelivered.append(profile_id)

    def get_stats(self) -> dict[str, int]:
        return {
            "queue_depth": len(self._undelivered),
            "undelivered_count": len(self._undelivered),
        }
