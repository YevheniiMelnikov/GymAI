from __future__ import annotations

from asyncio import TimeoutError as AsyncTimeoutError, sleep, timeout
from typing import Any, Callable

from aiohttp import web
from celery.app.control import Inspect
from celery.result import AsyncResult
from kombu import Connection
from kombu.exceptions import ChannelError

from config.app_settings import settings
from core.celery_app import app
from core.queues import AI_COACH_QUEUE


def _get_broker_url() -> str:
    broker_url_obj = getattr(app.conf, "broker_url", None)
    return str(broker_url_obj) if broker_url_obj else ""


def _queue_depth(broker_url: str) -> tuple[int, int]:
    with Connection(broker_url) as connection:
        channel = connection.channel()
        try:
            declaration = channel.queue_declare(queue=AI_COACH_QUEUE.name, passive=True)
            messages = int(getattr(declaration, "message_count", -1))
            consumers = int(getattr(declaration, "consumer_count", -1))
        finally:
            channel.close()
    return messages, consumers


def _serialise_result(result: AsyncResult) -> Any:
    if not result.ready():
        return None
    data = result.result
    if isinstance(data, (str, int, float, bool)) or data is None:
        return data
    if isinstance(data, (list, dict)):
        return data
    return str(data)


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
        "result": _serialise_result(result),
        "traceback": result.traceback,
    }
    return web.json_response(payload)


async def internal_celery_queue_depth(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    broker_url: str = _get_broker_url()
    if not broker_url:
        return web.json_response({"detail": "broker url is not configured"}, status=500)
    try:
        messages, consumers = _queue_depth(broker_url)
    except ChannelError as exc:
        return web.json_response({"detail": f"queue declare failed: {exc}"}, status=500)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"detail": f"queue inspect failed: {exc}"}, status=500)
    return web.json_response({"queue": AI_COACH_QUEUE.name, "messages": messages, "consumers": consumers})


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


async def internal_celery_worker_report(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    async_result = app.send_task(
        "core.tasks.ai_coach_worker_report",
        queue="ai_coach",
        routing_key="ai_coach",
    )
    result = AsyncResult(async_result.id, app=app)
    try:
        async with timeout(5):
            while not result.ready():
                await sleep(0.2)
    except AsyncTimeoutError:
        pass
    payload = {
        "task_id": result.id,
        "state": result.state,
        "ready": result.ready(),
        "result": _serialise_result(result),
    }
    return web.json_response(payload)


async def internal_celery_purge_ai_coach(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    broker_url: str = _get_broker_url()
    if not broker_url:
        return web.json_response({"detail": "broker url is not configured"}, status=500)
    try:
        with Connection(broker_url) as connection:
            channel = connection.channel()
            try:
                purged_count = channel.queue_purge(queue=AI_COACH_QUEUE.name)
            finally:
                channel.close()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"detail": f"queue purge failed: {exc}"}, status=500)
    return web.json_response({"queue": AI_COACH_QUEUE.name, "purged": int(purged_count or 0)})


async def internal_celery_smoke(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)
    broker_url: str = _get_broker_url()
    if not broker_url:
        return web.json_response({"detail": "broker url is not configured"}, status=500)

    queue_error: str | None = None
    try:
        before_messages, before_consumers = _queue_depth(broker_url)
    except ChannelError as exc:
        queue_error = f"queue declare failed before publish: {exc}"
        before_messages, before_consumers = -1, -1
    except Exception as exc:  # noqa: BLE001
        queue_error = f"queue inspect failed before publish: {exc}"
        before_messages, before_consumers = -1, -1

    async_result = app.send_task(
        "core.tasks.ai_coach_echo",
        args=({"smoke": True},),
        queue="ai_coach",
        routing_key="ai_coach",
    )
    result = AsyncResult(async_result.id, app=app)
    try:
        async with timeout(5):
            while not result.ready():
                await sleep(0.2)
    except AsyncTimeoutError:
        pass

    try:
        after_messages, after_consumers = _queue_depth(broker_url)
    except ChannelError as exc:
        if queue_error is None:
            queue_error = f"queue declare failed after publish: {exc}"
        after_messages, after_consumers = -1, -1
    except Exception as exc:  # noqa: BLE001
        if queue_error is None:
            queue_error = f"queue inspect failed after publish: {exc}"
        after_messages, after_consumers = -1, -1

    payload = {
        "task_id": result.id,
        "state": result.state,
        "ready": result.ready(),
        "result": _serialise_result(result),
        "queue": {
            "before": {"messages": before_messages, "consumers": before_consumers},
            "after": {"messages": after_messages, "consumers": after_consumers},
        },
    }
    if queue_error:
        payload["queue_error"] = queue_error
    return web.json_response(payload)


__all__ = [
    "internal_celery_debug",
    "internal_celery_result",
    "internal_celery_queue_depth",
    "internal_celery_submit_echo",
    "internal_celery_worker_report",
    "internal_celery_purge_ai_coach",
    "internal_celery_smoke",
]
