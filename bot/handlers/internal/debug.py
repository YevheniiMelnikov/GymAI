from __future__ import annotations

from typing import Any, Callable

from aiohttp import web
from celery.app.control import Inspect

from config.app_settings import settings
from core.celery_app import app


def _call_inspector(inspector: Inspect | None, method_name: str) -> Any:
    if inspector is None:
        return None
    try:
        method: Callable[[], Any] = getattr(inspector, method_name)
    except AttributeError:
        return {"error": f"method {method_name} unavailable"}
    try:
        return method()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def internal_celery_debug(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    inspector: Inspect | None = app.control.inspect()
    broker_url: str | None = getattr(app.conf, "broker_url", None)
    result_backend: str | None = getattr(app.conf, "result_backend", None)

    routes: dict[str, Any] = dict(app.conf.task_routes or {})

    payload: dict[str, Any] = {
        "broker_url": broker_url,
        "result_backend": result_backend,
        "active_queues": _call_inspector(inspector, "active_queues"),
        "registered": _call_inspector(inspector, "registered"),
        "active": _call_inspector(inspector, "active"),
        "reserved": _call_inspector(inspector, "reserved"),
        "scheduled": _call_inspector(inspector, "scheduled"),
        "routes": routes,
    }
    return web.json_response(payload)


__all__ = ["internal_celery_debug"]
