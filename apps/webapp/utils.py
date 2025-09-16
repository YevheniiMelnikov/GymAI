import asyncio
import hashlib
import hmac
import json
import re
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qsl

from config.app_settings import settings
from loguru import logger

from core.schemas import DayExercises

_DAY_INDEX_RE = re.compile(r"\d+")


async def ensure_container_ready() -> None:
    try:
        from core.containers import get_container

        container = get_container()
    except Exception:  # pragma: no cover - optional in tests
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

    if not (ok_new or ok_old):
        logger.error(
            "Init data verification failed",
            hash_preview=received_hash[:16],
            calc_new_preview=(calc_new or "")[:16],
            calc_old_preview=(calc_old or "")[:16],
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

    return result


def _extract_day_index(label: str) -> int | None:
    match = _DAY_INDEX_RE.search(label)
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def _sort_day_entries(entries: Iterable[tuple[int, str, Any]]) -> list[tuple[str, Any]]:
    def sort_key(item: tuple[int, str, Any]) -> tuple[int, int]:
        position, label, _ = item
        numeric = _extract_day_index(label)
        return (numeric if numeric is not None else position, position)

    ordered = sorted(entries, key=sort_key)
    return [(label, value) for _, label, value in ordered]


def normalize_day_exercises(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        entries = [(idx, str(key), value) for idx, (key, value) in enumerate(raw.items())]
        ordered = _sort_day_entries(entries)
        return [{"day": label, "exercises": value} for label, value in ordered]
    if isinstance(raw, list):
        return raw
    return []


def _sorted_exercises(exercises: Sequence[DayExercises]) -> list[DayExercises]:
    enumerated = [(idx, day) for idx, day in enumerate(exercises)]

    def sort_key(item: tuple[int, DayExercises]) -> tuple[int, int]:
        position, day = item
        numeric = _extract_day_index(day.day)
        return (numeric if numeric is not None else position, position)

    ordered = sorted(enumerated, key=sort_key)
    return [day for _, day in ordered]


def _format_full_program(exercises: list[DayExercises]) -> str:
    lines: list[str] = []
    for order, day in enumerate(_sorted_exercises(exercises)):
        label = day.day.strip()
        if label.isdigit():
            header = f"Day {int(label) + 1}"
        elif label:
            header = label
        else:
            header = f"Day {order + 1}"
        lines.append(header)
        for idx, ex in enumerate(day.exercises):
            line = f"{idx + 1}. {ex.name} | {ex.sets} x {ex.reps}"
            if ex.weight:
                line += f" | {ex.weight}"
            if ex.set_id is not None:
                line += f" | Set {ex.set_id}"
            if ex.drop_set:
                line += " | Drop set"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()
