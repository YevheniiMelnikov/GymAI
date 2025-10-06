from __future__ import annotations

from typing import Any, Callable

from aiohttp import web
from celery.app.control import Inspect
from celery.result import AsyncResult
from kombu import Connection
from kombu.exceptions import ChannelError

from config.app_settings import settings
from core.celery_app import app
from core.queues import AI_COACH_QUEUE


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


async def internal_celery_result(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    task_id = request.query.get("task_id")
    if not task_id:
        return web.json_response({"detail": "task_id is required"}, status=400)
    result = AsyncResult(task_id, app=app)
    payload: dict[str, Any] = {
        "id": result.id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "result": str(result.result) if result.ready() else None,
        "traceback": result.traceback,
    }
    return web.json_response(payload)


async def internal_celery_queue_depth(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    broker_url_obj = getattr(app.conf, "broker_url", None)
    broker_url: str | None = str(broker_url_obj) if broker_url_obj else None
    if not broker_url:
        return web.json_response({"detail": "broker url is not configured"}, status=500)
    declare_result: Any | None = None
    try:
        with Connection(broker_url) as connection:
            channel = connection.channel()
            try:
                declare_result = channel.queue_declare(
                    queue=AI_COACH_QUEUE.name,
                    passive=True,
                )
            finally:
                channel.close()
    except ChannelError as exc:
        return web.json_response({"detail": f"queue declare failed: {exc}"}, status=500)
    if declare_result is None:
        return web.json_response({"detail": "queue declare did not return statistics"}, status=500)
    messages: int = getattr(declare_result, "message_count", -1)
    consumers: int = getattr(declare_result, "consumer_count", -1)
    payload = {
        "queue": AI_COACH_QUEUE.name,
        "messages": messages,
        "consumers": consumers,
    }
    return web.json_response(payload)


async def internal_celery_submit_echo(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"detail": "Invalid JSON"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"detail": "Payload must be an object"}, status=400)
    async_result = app.send_task(
        "core.tasks.ai_coach_echo",
        args=(payload,),
        queue="ai_coach",
        routing_key="ai_coach",
    )
    return web.json_response({"task_id": async_result.id}, status=202)


__all__ = [
    "internal_celery_debug",
    "internal_celery_result",
    "internal_celery_queue_depth",
    "internal_celery_submit_echo",
]
