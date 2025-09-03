from __future__ import annotations

import aiohttp
from loguru import logger


async def short_url(url: str) -> str:
    """Return a TinyURL HTTPS link for the given URL."""
    if url.startswith("https://tinyurl.com/"):
        return url
    try:
        async with aiohttp.ClientSession() as session:
            params = {"url": url}
            async with session.get("https://tinyurl.com/api-create.php", params=params) as response:
                text = await response.text()
                if response.status == 200:
                    return text
                logger.error("Failed to short url status={} text={}", response.status, text)
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("TinyURL request failed: {}", exc)
    return url
