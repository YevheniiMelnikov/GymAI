from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Mapping, MutableMapping, cast

from celery import Task, signals
from loguru import logger

from core.celery_app import AI_COACH_TASK_ROUTES

REQUIRED_TASK_NAMES: tuple[str, ...] = tuple(AI_COACH_TASK_ROUTES.keys())
_TASK_START_TIMES: MutableMapping[str, float] = {}
_SIGNALS_ATTACHED: bool = False


def setup_celery_signals() -> None:
    global _SIGNALS_ATTACHED
    if _SIGNALS_ATTACHED:
        return
    signals.worker_ready.connect(_on_worker_ready, weak=False)
    signals.task_prerun.connect(_on_task_prerun, weak=False)
    signals.task_postrun.connect(_on_task_postrun, weak=False)
    signals.after_setup_task_logger.connect(_on_after_setup_task_logger, weak=False)
    _SIGNALS_ATTACHED = True


def _on_after_setup_task_logger(logger_: logging.Logger, **_: Any) -> None:
    logger_.setLevel(logging.INFO)


def _on_worker_ready(sender: Any, **_: Any) -> None:
    from celery.apps.worker import WorkController  # local import for typing only

    worker: WorkController = cast(WorkController, sender)
    inspect = worker.app.control.inspect(destination=[worker.hostname])

    queue_names: list[str] = []
    if inspect is not None:
        active_queues = inspect.active_queues() or {}
        worker_queues = active_queues.get(worker.hostname) or []
        queue_names = sorted({str(queue.get("name")) for queue in worker_queues if queue.get("name")})

    if not queue_names and getattr(worker, "consumer", None) is not None:
        consumer = worker.consumer
        queues_iter: Iterable[Any] = getattr(consumer, "queues", [])
        queue_names = sorted({str(getattr(queue, "name", "")) for queue in queues_iter if getattr(queue, "name", "")})

    registered_missing: list[str] = []
    registered_ok: bool = False
    if inspect is not None:
        registered_map = inspect.registered() or inspect.registered_tasks() or {}
        worker_registered = set(registered_map.get(worker.hostname) or [])
        registered_missing = [name for name in REQUIRED_TASK_NAMES if name not in worker_registered]
        registered_ok = not registered_missing
    else:
        registered_ok = all(name in worker.app.tasks for name in REQUIRED_TASK_NAMES)

    logger.info(
        f"celery_ready hostname={worker.hostname} queues={queue_names} "
        f"registered_ok={registered_ok} missing={registered_missing}"
    )

    if "ai_coach" not in queue_names:
        logger.error(f"ai_coach queue missing on worker hostname={worker.hostname} queues={queue_names}")
        raise SystemExit("ai_coach queue is not registered on this worker")

    if not registered_ok:
        logger.error(
            "celery tasks missing "
            f"hostname={worker.hostname} missing={registered_missing} "
            f"available={sorted(worker.app.tasks.keys())}"
        )
        raise SystemExit("Required Celery tasks are not registered")


def _on_task_prerun(task_id: str, task: Task, **_: Any) -> None:
    if task.name not in REQUIRED_TASK_NAMES:
        return
    request_id, retries = _extract_request_context(task)
    _TASK_START_TIMES[task_id] = time.perf_counter()
    logger.info(f"celery_task_start name={task.name} task_id={task_id} request_id={request_id} retries={retries}")


def _on_task_postrun(task_id: str, task: Task, state: str, retval: Any, **_: Any) -> None:
    if task.name not in REQUIRED_TASK_NAMES:
        return
    start_time = _TASK_START_TIMES.pop(task_id, None)
    duration_ms: float | None = None
    if start_time is not None:
        duration_ms = (time.perf_counter() - start_time) * 1000
    request_id, retries = _extract_request_context(task)
    duration_value: float = duration_ms or 0.0
    logger.info(
        "celery_task_done "
        f"name={task.name} task_id={task_id} request_id={request_id} "
        f"retries={retries} state={state} duration_ms={duration_value:.2f}"
    )


def _extract_request_context(task: Task) -> tuple[str | None, int]:
    request = getattr(task, "request", None)
    if request is None:
        return None, 0
    retries = int(getattr(request, "retries", 0))
    request_id: str | None = None
    if hasattr(request, "kwargs"):
        kwargs = getattr(request, "kwargs", {})
        if isinstance(kwargs, Mapping):
            raw_request_id = kwargs.get("request_id")
            if raw_request_id is None:
                args = getattr(request, "args", None)
                if args:
                    payload = args[0]
                    if isinstance(payload, Mapping):
                        raw_request_id = payload.get("request_id")
            if raw_request_id is not None:
                request_id = str(raw_request_id)
    return request_id, retries


__all__ = [
    "setup_celery_signals",
]
