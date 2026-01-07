from urllib.parse import urlsplit, urlunsplit, ParseResult, urlparse, parse_qsl, urlencode, urlunparse

from loguru import logger

from bot.utils.bot import _WEBAPP_TARGETS
from config.app_settings import settings


def normalize_support_contact(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return value
    if value.startswith("@"):
        value = value[1:]
    if value.startswith("t.me/") or value.startswith("telegram.me/"):
        return f"https://{value}"
    return f"https://t.me/{value}"


def support_contact_url() -> str:
    return normalize_support_contact(settings.TG_SUPPORT_CONTACT) or settings.TG_SUPPORT_CONTACT or ""


def build_ping_url(webhook_url: str | None) -> str:
    if webhook_url is None:
        raise ValueError("webhook_url must be set")
    s = urlsplit(webhook_url)
    path = settings.WEBHOOK_PATH.rstrip("/") + "/__ping"
    return urlunsplit((s.scheme, s.netloc, path, "", ""))


def get_webapp_url(
    page_type: str,
    lang: str | None = None,
    extra_params: dict[str, str] | None = None,
) -> str | None:
    source = settings.WEBAPP_PUBLIC_URL
    if not source:
        logger.error("WEBAPP_PUBLIC_URL is not configured; webapp button hidden")
        return None

    target = _WEBAPP_TARGETS.get(page_type, _WEBAPP_TARGETS["program"])
    parsed: ParseResult = urlparse(source)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params["type"] = target.type_param

    if target.source:
        query_params["source"] = target.source
    else:
        query_params.pop("source", None)

    if target.segment:
        query_params["segment"] = target.segment
    else:
        query_params.pop("segment", None)

    if lang:
        query_params["lang"] = lang
    else:
        query_params.pop("lang", None)

    merged_params = dict(query_params)
    if extra_params:
        for key, value in extra_params.items():
            if value is None:
                merged_params.pop(key, None)
                continue
            merged_params[str(key)] = str(value)

    fragment = (target.fragment or "").lstrip("#")
    new_query = urlencode(merged_params)
    path = parsed.path or "/webapp/"
    updated = parsed._replace(path=path, query=new_query, fragment=fragment)
    return str(urlunparse(updated))
