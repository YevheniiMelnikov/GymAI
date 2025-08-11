from __future__ import annotations

import re
import secrets
import string
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import aiohttp

from loguru import logger


async def short_url(url: str) -> str:
    if url.startswith("https://tinyurl.com/"):
        return url

    async with aiohttp.ClientSession() as session:
        params = {"url": url}
        async with session.get("http://tinyurl.com/api-create.php", params=params) as response:
            response_text = await response.text()
            if response.status == 200:
                return response_text
            else:
                logger.error(f"Failed to process URL: {response.status}, {response_text}")
                return url


def generate_order_id() -> str:
    characters = string.ascii_letters + string.digits
    return "".join(secrets.choice(characters) for _ in range(12))


def parse_price(raw: str) -> Decimal:
    price_re = re.compile(r"^\d{1,8}(\.\d{1,2})?$")

    if not price_re.fullmatch(raw):
        raise ValueError("Price must be 0-99 999 999.99 (max 2 decimals)")
    try:
        return Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value") from exc
