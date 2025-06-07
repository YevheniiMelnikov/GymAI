from typing import cast
from loguru import logger

from base import BaseCacheManager
from core.enums import PaymentStatus
from core.services import PaymentService
from core.exceptions import PaymentNotFoundError


class PaymentCacheManager(BaseCacheManager):
    service = PaymentService
    _PREFIX = "workout_plans:payments"

    @classmethod
    def _key(cls, service_type: str) -> str:
        return f"{cls._PREFIX}:{service_type}"

    @classmethod
    async def set_status(cls, client_id: int, service_type: str, status: PaymentStatus) -> None:
        try:
            await cls.set_json(cls._key(service_type), str(client_id), {"status": status.value})
            logger.debug(f"Payment status cached: client_id={client_id}, type={service_type}, status={status}")
        except Exception as e:
            logger.error(f"Failed to cache payment status for client_id={client_id}: {e}")

    @classmethod
    async def reset_status(cls, client_id: int, service_type: str) -> None:
        try:
            await cls.delete(cls._key(service_type), str(client_id))
            logger.debug(f"Payment status reset for client_id={client_id}, type={service_type}")
        except Exception as e:
            logger.error(f"Failed to reset payment status for client_id={client_id}: {e}")

    @classmethod
    async def get_status(cls, client_id: int, service_type: str, *, use_fallback: bool = True) -> PaymentStatus:
        raw = await cls.get_json(cls._key(service_type), str(client_id))
        if raw and "status" in raw:
            try:
                return cast(PaymentStatus, PaymentStatus(raw["status"]))
            except (ValueError, KeyError):
                await cls.delete(cls._key(service_type), str(client_id))
                logger.debug(f"Corrupt payment status for client_id={client_id}")

        if not use_fallback:
            raise PaymentNotFoundError(client_id)

        payment = await cls.service.get_latest_payment(client_id, service_type)
        if payment is None:
            raise PaymentNotFoundError(client_id)

        try:
            status = cast(PaymentStatus, PaymentStatus(payment.status))
        except (ValueError, KeyError):
            logger.error(f"Invalid payment status '{payment.status}' for client_id={client_id}")
            status = PaymentStatus.PENDING

        await cls.set_status(client_id, service_type, status)
        return status

    @classmethod
    async def is_payed(cls, client_id: int, service_type: str) -> bool:
        try:
            return (await cls.get_status(client_id, service_type)) in (PaymentStatus.SUCCESS, PaymentStatus.CLOSED)
        except PaymentNotFoundError:
            return False
