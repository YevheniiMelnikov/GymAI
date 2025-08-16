import hashlib
import hmac
import json
from typing import cast
from urllib.parse import parse_qsl

from config.app_settings import settings


def verify_init_data(init_data: str) -> dict[str, object]:
    data: dict[str, str] = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash: str | None = data.pop("hash", None)
    check_string: str = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key: bytes = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
    calculated_hash: str = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if calculated_hash != received_hash:
        raise ValueError("Invalid init data")
    if "user" in data:
        data["user"] = json.loads(data["user"])
    return cast(dict[str, object], data)
