from typing import Any
from loguru import logger
import json

from .base import BaseCacheManager
from core.enums import PaymentStatus
from core.containers import get_container
from core.exceptions import PaymentNotFoundError


class PaymentCacheManager(BaseCacheManager):
    _PREFIX = "workout_plans:payments"

    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> PaymentStatus:
        service_type = cache_key.split(":")[-1]
        service = get_container().payment_service()
        payment = await service.get_latest_payment(int(field), service_type)
        if payment is None:
            raise PaymentNotFoundError(int(field))
        try:
            return PaymentStatus(payment.status)
        except (ValueError, KeyError):
            logger.error(f"Invalid payment status '{payment.status}' for profile_id={field}")
            return PaymentStatus.PENDING

    @classmethod
    def _prepare_for_cache(cls, data: Any, cache_key: str, field: str) -> dict:
        status: PaymentStatus = data
        return {"status": status.value}

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> PaymentStatus:
        try:
            data = json.loads(raw)
            if "status" in data:
                return PaymentStatus(data["status"])
        except Exception:
            pass
        raise PaymentNotFoundError(int(field))

    @classmethod
    def _key(cls, service_type: str) -> str:
        return f"{cls._PREFIX}:{service_type}"

    @classmethod
    async def set_status(cls, profile_id: int, service_type: str, status: PaymentStatus) -> None:
        try:
            await cls.set_json(cls._key(service_type), str(profile_id), {"status": status.value})
            logger.debug(f"Payment status cached: profile_id={profile_id}, type={service_type}, status={status}")
        except Exception as e:
            logger.error(f"Failed to cache payment status for profile_id={profile_id}: {e}")

    @classmethod
    async def reset_status(cls, profile_id: int, service_type: str) -> None:
        try:
            await cls.delete(cls._key(service_type), str(profile_id))
            logger.debug(f"Payment status reset for profile_id={profile_id}, type={service_type}")
        except Exception as e:
            logger.error(f"Failed to reset payment status for profile_id={profile_id}: {e}")

    @classmethod
    async def get_status(cls, profile_id: int, service_type: str, *, use_fallback: bool = True) -> PaymentStatus:
        return await cls.get_or_fetch(cls._key(service_type), str(profile_id), use_fallback=use_fallback)

    @classmethod
    async def is_payed(cls, profile_id: int, service_type: str) -> bool:
        try:
            return (await cls.get_status(profile_id, service_type)) == PaymentStatus.SUCCESS
        except PaymentNotFoundError:
            return False
