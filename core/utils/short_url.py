try:  # network dependencies are optional in tests
    import aiohttp
except Exception:  # pragma: no cover - fallback when aiohttp missing
    aiohttp = None

try:
    from loguru import logger
except Exception:  # pragma: no cover - simple logger stub

    class _Logger:
        def error(self, *args, **kwargs) -> None:  # type: ignore[empty-body]
            return None

    logger = _Logger()


async def short_url(url: str) -> str:
    """Return a TinyURL HTTPS link for the given URL."""
    if url.startswith("https://tinyurl.com/"):
        return url
    if aiohttp is None:
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
