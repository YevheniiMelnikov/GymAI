def memify_run_at_key(profile_id: int) -> str:
    return f"ai_coach:memify:profile:{profile_id}:run_at"


def memify_scheduled_key(profile_id: int) -> str:
    return f"ai_coach:memify:profile:{profile_id}:scheduled"


def memify_schedule_ttl(delay_s: float) -> int:
    ttl = int(max(delay_s, 0.0)) + 600
    return max(ttl, 600)


def parse_memify_run_at(raw_value: str | None) -> float | None:
    if not raw_value:
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None
