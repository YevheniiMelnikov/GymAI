import asyncio
import hashlib
import hmac
import json
from typing import Any, cast
from urllib.parse import parse_qsl

from config.app_settings import settings
from loguru import logger

from core.schemas import DayExercises


async def ensure_container_ready() -> None:
    try:
        from core.containers import get_container

        container = get_container()
    except Exception:  # pragma: no cover - container not required for tests
        return
    if hasattr(container, "init_resources"):
        maybe = container.init_resources()
        if asyncio.iscoroutine(maybe):
            await maybe


def _hash_webapp(token: str, check_string: str) -> str:
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_legacy(token: str, check_string: str) -> str:
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str) -> dict[str, object]:
    items = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = (items.pop("hash", "") or "").lower()
    if not received_hash:
        raise ValueError("Invalid init data")

    signature = items.pop("signature", None)
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
        f"verify_init_data: keys={sorted(items.keys())} "
        f"recv_hash={received_hash[:16]} calc_new={(calc_new or '')[:16]} "
        f"calc_old={(calc_old or '')[:16]} token_head={token[:12]} "
        f"check_len={len(check_string)}"
    )

    if not (ok_new or ok_old):
        logger.warning(
            f"verify_init_data mismatch: token_head={token[:12]} recv={received_hash} "
            f"calc_new={calc_new} calc_old={calc_old} check={check_string!r}"
        )
        raise ValueError("Invalid init data")

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

    user = result.get("user")
    user_id = user.get("id") if isinstance(user, dict) else None
    logger.debug(f"verify_init_data ok (scheme={'new' if ok_new else 'old'}) for user_id={user_id}")
    return cast(dict[str, object], result)


def normalize_day_exercises(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [{"day": str(k), "exercises": v} for k, v in sorted(raw.items(), key=lambda kv: int(str(kv[0])))]
    if isinstance(raw, list):
        return raw
    return []


def _format_full_program(exercises: list[DayExercises]) -> str:
    lines: list[str] = []
    for day in sorted(exercises, key=lambda d: int(d.day)):
        lines.append(f"Day {int(day.day) + 1}")
        for idx, ex in enumerate(day.exercises):
            line = f"{idx + 1}. {ex.name} | {ex.sets} x {ex.reps}"
            if ex.weight:
                line += f" | {ex.weight} kg"
            if ex.set_id is not None:
                line += f" | Set {ex.set_id}"
            if ex.drop_set:
                line += " | Drop set"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()
