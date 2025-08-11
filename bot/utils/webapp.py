from urllib.parse import urlparse

from loguru import logger

from config.app_settings import settings


def get_webapp_url(page_type: str) -> str | None:
    source = settings.WEBAPP_PUBLIC_URL
    if not source:
        logger.error("WEBAPP_PUBLIC_URL is not configured; webapp button hidden")
        return None
    parsed = urlparse(source)
    host = parsed.netloc or parsed.path.split("/")[0]
    base = f"{parsed.scheme or 'https'}://{host}"
    return f"{base}/webapp/?type={page_type}"
