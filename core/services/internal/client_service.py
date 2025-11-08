from typing import Any

from loguru import logger

from core.domain.profile_repository import ProfileRepository
from core.schemas import Client
from .api_client import APIClientHTTPError


class ClientService:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def charge_credits(self, client_id: int, cost: int) -> Client:
        if cost <= 0:
            logger.debug(f"client_charge_skipped client_id={client_id} cost={cost}")
            client = await self._repository.get_client(client_id)
            if client is None:
                raise self._not_found_error(client_id, action="charge")
            return client
        client = await self._repository.get_client(client_id)
        if client is None:
            raise self._not_found_error(client_id, action="charge")
        if client.credits < cost:
            raise APIClientHTTPError(
                status=402,
                text="insufficient_credits",
                method="POST",
                url=f"internal:client:{client_id}:charge_credits",
                retryable=False,
                reason="insufficient_credits",
            )
        updated = await self._update_client_credits(client, client.credits - cost, action="charge")
        logger.debug(
            f"client_charge_success client_id={client_id} cost={cost} "
            f"balance_before={client.credits} balance_after={updated.credits}"
        )
        return updated

    async def refund_credits(self, client_id: int, amount: int) -> Client:
        if amount <= 0:
            logger.debug(f"client_refund_skipped client_id={client_id} amount={amount}")
            client = await self._repository.get_client(client_id)
            if client is None:
                raise self._not_found_error(client_id, action="refund")
            return client
        client = await self._repository.get_client(client_id)
        if client is None:
            raise self._not_found_error(client_id, action="refund")
        target_balance = client.credits + amount
        updated = await self._update_client_credits(client, target_balance, action="refund")
        logger.debug(
            f"client_refund_success client_id={client_id} amount={amount} "
            f"balance_before={client.credits} balance_after={updated.credits}"
        )
        return updated

    async def _update_client_credits(self, client: Client, value: int, *, action: str) -> Client:
        payload: dict[str, Any] = {"credits": max(0, int(value))}
        ok = await self._repository.update_client_profile(client.id, payload)
        if not ok:
            raise APIClientHTTPError(
                status=500,
                text=f"{action}_failed",
                method="PATCH",
                url=f"internal:client:{client.id}:{action}_credits",
                retryable=False,
                reason=f"{action}_failed",
            )
        refreshed = await self._repository.get_client(client.id)
        if refreshed is None:
            raise self._not_found_error(client.id, action=action)
        return refreshed

    @staticmethod
    def _not_found_error(client_id: int, *, action: str) -> APIClientHTTPError:
        return APIClientHTTPError(
            status=404,
            text="client_not_found",
            method="GET",
            url=f"internal:client:{client_id}:{action}_credits",
            retryable=False,
            reason="client_not_found",
        )
