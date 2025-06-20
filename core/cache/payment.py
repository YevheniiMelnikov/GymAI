from typing import Any, cast
from loguru import logger
import json

from .base import BaseCacheManager
from core.enums import PaymentStatus
from core.services.payment_service import PaymentService
from core.exceptions import PaymentNotFoundError


class PaymentCacheManager(BaseCacheManager):
    service = PaymentService
    _PREFIX = "workout_plans:payments"

    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> PaymentStatus:
        service_type = cache_key.split(":")[-1]
        payment = await cls.service.get_latest_payment(int(field), service_type)
        if payment is None:
            raise PaymentNotFoundError(int(field))
        try:
            return cast(PaymentStatus, PaymentStatus(payment.status))
        except (ValueError, KeyError):
            logger.error(f"Invalid payment status '{payment.status}' for client_id={field}")
            return PaymentStatus.PENDING

    @classmethod
    def _prepare_for_cache(cls, data: Any, cache_key: str, field: str) -> dict:
        status = cast(PaymentStatus, data)
        return {"status": status.value}

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> PaymentStatus:
        try:
            data = json.loads(raw)
            if "status" in data:
                return cast(PaymentStatus, PaymentStatus(data["status"]))
        except Exception:
            pass
        raise PaymentNotFoundError(int(field))

    @classmethod
    def _key(cls, service_type: str) -> str:
        return f"{cls._PREFIX}:{service_type}"

    @classmethod
    async def set_status(cls, client_profile_id: int, service_type: str, status: PaymentStatus) -> None:
        try:
            await cls.set_json(cls._key(service_type), str(client_profile_id), {"status": status.value})
            logger.debug(
                f"Payment status cached: client_profile_id={client_profile_id}, type={service_type}, status={status}"
            )
        except Exception as e:
            logger.error(f"Failed to cache payment status for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def reset_status(cls, client_profile_id: int, service_type: str) -> None:
        try:
            await cls.delete(cls._key(service_type), str(client_profile_id))
            logger.debug(f"Payment status reset for client_profile_id={client_profile_id}, type={service_type}")
        except Exception as e:
            logger.error(f"Failed to reset payment status for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def get_status(cls, client_profile_id: int, service_type: str, *, use_fallback: bool = True) -> PaymentStatus:
        return await cls.get_or_fetch(cls._key(service_type), str(client_profile_id), use_fallback=use_fallback)

    @classmethod
    async def is_payed(cls, client_profile_id: int, service_type: str) -> bool:
        try:
            return (await cls.get_status(client_profile_id, service_type)) in (
                PaymentStatus.SUCCESS,
                PaymentStatus.CLOSED,
            )
        except PaymentNotFoundError:
            return False
