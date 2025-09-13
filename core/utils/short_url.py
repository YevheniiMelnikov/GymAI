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
                logger.error(f"Failed to short url status={response.status} text={text}")
    except Exception as exc:  # pragma: no cover - network errors
        logger.error(f"TinyURL request failed: {exc}")
    return url
