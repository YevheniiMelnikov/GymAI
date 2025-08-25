# apps/webapp/utils.py
import hashlib
import hmac
import json
from typing import cast
from urllib.parse import parse_qsl, unquote_plus

from config.app_settings import settings
from loguru import logger


def _hash_webapp(token: str, check_string: str) -> str:
    """Новая схема (WebApp): secret = HMAC_SHA256(b"WebAppData", token)"""
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_legacy(token: str, check_string: str) -> str:
    """Старая схема (Login/часть клиентов): secret = SHA256(token)"""
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str) -> dict[str, object]:
    """
    Проверка подписи Telegram WebApp initData.
    ВАЖНО: в data_check_string должны входить все пары k=v, кроме 'hash'.
           'signature' оставляем, если она присутствует.
    Поддерживаем обе схемы:
      1) Новая  — secret = HMAC_SHA256(b"WebAppData", bot_token)
      2) Старая — secret = SHA256(bot_token)
    """
    decoded = unquote_plus(init_data)
    items = dict(parse_qsl(decoded, keep_blank_values=True))

    received_hash = (items.pop("hash", "") or "").lower()
    if not received_hash:
        raise ValueError("Invalid init data")

    # НЕ удаляем 'signature' — она должна участвовать в подписи, если присутствует
    signature = items.get("signature")

    # Строка для подписи: сортируем все оставшиеся пары (включая signature, user и т.п.)
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(items.items()))

    token: str = settings.BOT_TOKEN or ""
    if not token:
        raise ValueError("Invalid init data")

    calc_new = _hash_webapp(token, check_string)
    ok_new = hmac.compare_digest(calc_new, received_hash)

    if not ok_new:
        calc_old = _hash_legacy(token, check_string)
        ok_old = hmac.compare_digest(calc_old, received_hash)
    else:
        calc_old = None
        ok_old = False

    logger.debug(
        "verify_init_data: keys={} recv_hash={} calc_new={} calc_old={} token_head={} check_len={}",
        sorted(items.keys()),
        received_hash[:16],
        (calc_new or "")[:16],
        (calc_old or "")[:16],
        token[:12],
        len(check_string),
    )

    if not (ok_new or ok_old):
        logger.warning(
            "verify_init_data mismatch: token_head={} recv={} calc_new={} calc_old={} check={!r}",
            token[:12],
            received_hash,
            calc_new,
            calc_old,
            check_string,
        )
        raise ValueError("Invalid init data")

    # Сформируем результирующий словарь, аккуратно парсим JSON-поля
    result: dict[str, object] = {}
    for k, v in items.items():
        if k in {"user", "chat", "receiver"}:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
        else:
            result[k] = v
    if signature is not None:
        result["signature"] = signature

    logger.debug(
        "verify_init_data ok (scheme={}) for user_id={}",
        "new" if ok_new else "old",
        (result.get("user") or {}).get("id") if isinstance(result.get("user"), dict) else None,
    )
    return cast(dict[str, object], result)
