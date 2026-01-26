from __future__ import annotations

from urllib.parse import urljoin

import httpx

from config.app_settings import settings


def sync_profile_dataset(profile_id: int, *, reason: str = "eval") -> dict[str, object]:
    payload = {"reason": reason}
    base_url = settings.AI_COACH_URL.rstrip("/") + "/"
    url = urljoin(base_url, f"knowledge/profiles/{profile_id}/sync/")
    auth = (settings.AI_COACH_REFRESH_USER, settings.AI_COACH_REFRESH_PASSWORD)
    timeout = float(settings.AI_COACH_TIMEOUT)
    response = httpx.post(url, json=payload, auth=auth, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {"indexed": False, "detail": "unexpected_response"}
