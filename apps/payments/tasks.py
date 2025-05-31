import httpx
from celery import shared_task
from loguru import logger

from config.env_settings import Settings


@shared_task(bind=True, max_retries=3, retry_backoff=30, retry_backoff_max=300)
def process_payment_webhook(self, order_id: str, status: str, err_description: str = "") -> None:
    async def _call_bot() -> None:
        url = f"{Settings.BOT_INTERNAL_URL}/internal/payment/process/"
        payload = {
            "order_id": order_id,
            "status": status,
            "err_description": err_description,
        }
        headers = {"Authorization": f"Api-Key {Settings.API_KEY}"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

    try:
        import asyncio

        asyncio.run(_call_bot())

    except Exception as exc:
        logger.warning(f"Bot call failed for order_id={order_id}: {exc}")
        raise self.retry(exc=exc)
