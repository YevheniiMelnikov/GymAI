from __future__ import annotations

import json
from typing import Any

from evals.ask_ai.config import SCENARIOS_DIR


def load_profile_fixture(*, scenario: str) -> dict[str, Any]:
    target = SCENARIOS_DIR / scenario / "profile.json"
    if not target.exists():
        raise FileNotFoundError(f"scenario_profile_missing:{target}")
    return json.loads(target.read_text(encoding="utf-8"))


def ensure_eval_profile(data: dict[str, Any]):
    from apps.profiles.models import Profile

    profile, _ = Profile.objects.update_or_create(
        tg_id=data["tg_id"],
        defaults=data,
    )
    return profile


def profile_text(profile_data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in profile_data.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}: {', '.join(map(str, value))}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
