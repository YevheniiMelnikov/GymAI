import importlib
import os
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

import pytest

try:
    import dateutil  # noqa: F401
except ModuleNotFoundError:
    dateutil_module = ModuleType("dateutil")
    relativedelta_module = ModuleType("dateutil.relativedelta")

    class _Relativedelta:  # pragma: no cover - stub for optional dependency
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    relativedelta_module.relativedelta = _Relativedelta
    dateutil_module.relativedelta = relativedelta_module
    sys.modules.setdefault("dateutil", dateutil_module)
    sys.modules.setdefault("dateutil.relativedelta", relativedelta_module)

try:
    import kombu  # noqa: F401
except ModuleNotFoundError:
    kombu_module = ModuleType("kombu")

    class _Exchange:  # pragma: no cover - stub for tests
        def __init__(self, name: str, *args: Any, **kwargs: Any) -> None:
            self.name = name

    class _Queue:  # pragma: no cover - stub for tests
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    kombu_module.Exchange = _Exchange
    kombu_module.Queue = _Queue
    sys.modules.setdefault("kombu", kombu_module)

celery_module = ModuleType("celery")


class _Task:  # pragma: no cover - stub for tests
    request: SimpleNamespace


class _Conf:  # pragma: no cover - stub for tests
    def update(self, **kwargs: Any) -> None:
        self.settings = kwargs


class _Celery:  # pragma: no cover - stub for tests
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.conf = _Conf()

    def task(self, *args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator


celery_module.Task = _Task
celery_module.Celery = _Celery
sys.modules["celery"] = celery_module

if "core.celery_app" not in sys.modules:
    celery_app_module = ModuleType("core.celery_app")

    class _AppConf:  # pragma: no cover - stub for tests
        def update(self, **kwargs: Any) -> None:
            self.options = kwargs

    class _App:  # pragma: no cover - stub for tests
        def __init__(self) -> None:
            self.conf = _AppConf()

        def task(self, *args: Any, **kwargs: Any):
            def decorator(func):
                return func

            return decorator

    celery_app_module.app = _App()
    sys.modules.setdefault("core.celery_app", celery_app_module)

redis_asyncio_module = ModuleType("redis.asyncio")
redis_asyncio_client_module = ModuleType("redis.asyncio.client")


class _Pipeline:  # pragma: no cover - stub for tests
    pass


redis_asyncio_client_module.Pipeline = _Pipeline
redis_asyncio_module.Redis = SimpleNamespace  # type: ignore[assignment]
redis_asyncio_module.client = redis_asyncio_client_module
sys.modules["redis.asyncio"] = redis_asyncio_module
sys.modules["redis.asyncio.client"] = redis_asyncio_client_module

os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


class _SettingsStub(SimpleNamespace):
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - defensive default
        if name.endswith(("_TIMEOUT", "_TTL", "_DAYS")):
            return 0
        return "stub"


_REQUIRED_SETTINGS: dict[str, Any] = {
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672//",
    "AI_COACH_TIMEOUT": 300,
    "AI_PLAN_NOTIFY_TIMEOUT": 120,
    "AI_PLAN_DEDUP_TTL": 3600,
    "AI_PLAN_NOTIFY_FAILURE_TTL": 3600,
    "DB_NAME": "db",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "user",
    "REDIS_URL": "redis://localhost:6379/0",
    "BACKUP_RETENTION_DAYS": 7,
    "BOT_INTERNAL_URL": "http://bot:8000/",
    "API_KEY": "api",
    "INTERNAL_API_KEY": "internal",
    "INTERNAL_HTTP_CONNECT_TIMEOUT": 5.0,
    "INTERNAL_HTTP_READ_TIMEOUT": 10.0,
    "API_TIMEOUT": 10,
}

settings = _SettingsStub(**_REQUIRED_SETTINGS)
sys.modules["config.app_settings"].settings = settings

ai_coach_tasks = importlib.import_module("core.tasks.ai_coach")


class DummyResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ai_coach_tasks.httpx.HTTPStatusError(
                "error",
                request=ai_coach_tasks.httpx.Request("POST", "http://example.com"),
                response=ai_coach_tasks.httpx.Response(self.status_code),
            )


class DummyClient:
    def __init__(self, recorder: dict[str, Any], *, timeout: Any) -> None:
        recorder["timeout"] = timeout
        self._recorder = recorder
        self._response_factory: Callable[[], DummyResponse] = lambda: DummyResponse(200)

    async def __aenter__(self) -> "DummyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
        return False

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> DummyResponse:
        self._recorder["url"] = url
        self._recorder["json"] = json
        self._recorder["headers"] = headers
        return self._response_factory()


class DummyState:
    def __init__(self) -> None:
        self.delivered: set[str] = set()
        self.failed: set[str] = set()

    async def is_delivered(self, plan_id: str) -> bool:
        return plan_id in self.delivered

    async def is_failed(self, plan_id: str) -> bool:
        return plan_id in self.failed

    async def mark_delivered(self, plan_id: str, ttl_s: int | None = None) -> None:
        self.delivered.add(plan_id)

    async def mark_failed(self, plan_id: str, reason: str, ttl_s: int | None = None) -> None:
        self.failed.add(plan_id)


@pytest.mark.asyncio
async def test_notify_ai_plan_ready_uses_internal_header(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder: dict[str, Any] = {}

    monkeypatch.setattr(settings, "BOT_INTERNAL_URL", "http://bot:8000/")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(settings, "API_KEY", "fallback")
    monkeypatch.setattr(settings, "INTERNAL_HTTP_CONNECT_TIMEOUT", 5.0)
    monkeypatch.setattr(settings, "INTERNAL_HTTP_READ_TIMEOUT", 12.0)

    monkeypatch.setattr(ai_coach_tasks, "AiPlanState", SimpleNamespace(create=lambda: DummyState()))
    monkeypatch.setattr(ai_coach_tasks.httpx, "AsyncClient", lambda **kwargs: DummyClient(recorder, **kwargs))

    payload = {
        "client_id": 1,
        "plan_type": "program",
        "status": "success",
        "action": "create",
        "request_id": "req-1",
        "plan": {"foo": "bar"},
    }

    await ai_coach_tasks._notify_ai_plan_ready(payload)

    assert recorder["headers"] == {"X-Internal-Api-Key": "secret"}
    timeout = recorder["timeout"]
    if hasattr(timeout, "connect"):
        assert timeout.connect == 5.0
        assert timeout.read == 12.0
    else:
        assert timeout == 12.0


@pytest.mark.asyncio
async def test_notify_ai_plan_ready_fallback_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder: dict[str, Any] = {}

    monkeypatch.setattr(settings, "BOT_INTERNAL_URL", "http://bot:8000/")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    monkeypatch.setattr(settings, "API_KEY", "fallback")
    monkeypatch.setattr(settings, "INTERNAL_HTTP_CONNECT_TIMEOUT", 3.0)
    monkeypatch.setattr(settings, "INTERNAL_HTTP_READ_TIMEOUT", 9.0)

    monkeypatch.setattr(ai_coach_tasks, "AiPlanState", SimpleNamespace(create=lambda: DummyState()))
    monkeypatch.setattr(ai_coach_tasks.httpx, "AsyncClient", lambda **kwargs: DummyClient(recorder, **kwargs))

    payload = {
        "client_id": 2,
        "plan_type": "program",
        "status": "error",
        "action": "update",
        "request_id": "req-2",
        "error": "oops",
    }

    await ai_coach_tasks._notify_ai_plan_ready(payload)

    assert recorder["headers"] == {"Authorization": "Api-Key fallback"}


@pytest.mark.asyncio
async def test_notify_ai_plan_ready_skips_duplicate_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder: dict[str, Any] = {"calls": 0}

    state = DummyState()
    state.delivered.add("req-3")

    monkeypatch.setattr(settings, "BOT_INTERNAL_URL", "http://bot:8000/")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(settings, "API_KEY", "fallback")
    monkeypatch.setattr(settings, "INTERNAL_HTTP_CONNECT_TIMEOUT", 1.0)
    monkeypatch.setattr(settings, "INTERNAL_HTTP_READ_TIMEOUT", 2.0)

    monkeypatch.setattr(ai_coach_tasks, "AiPlanState", SimpleNamespace(create=lambda: state))

    async def _noop_post(url: str, json: dict[str, Any], headers: dict[str, str]) -> DummyResponse:
        recorder["calls"] += 1
        return DummyResponse()

    class CountingClient(DummyClient):
        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> DummyResponse:
            recorder["calls"] += 1
            return await _noop_post(url, json, headers)

    monkeypatch.setattr(ai_coach_tasks.httpx, "AsyncClient", lambda **kwargs: CountingClient(recorder, **kwargs))

    payload = {
        "client_id": 3,
        "plan_type": "program",
        "status": "success",
        "action": "create",
        "request_id": "req-3",
        "plan": {"foo": "bar"},
    }

    await ai_coach_tasks._notify_ai_plan_ready(payload)

    assert recorder["calls"] == 0


@pytest.mark.asyncio
async def test_claim_plan_request_logs_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    class DuplicateState:
        async def claim_delivery(self, plan_id: str, ttl_s: int | None = None) -> bool:
            return False

    dummy_logger_calls: list[str] = []

    monkeypatch.setattr(ai_coach_tasks, "AiPlanState", SimpleNamespace(create=lambda: DuplicateState()))
    monkeypatch.setattr(settings, "AI_PLAN_DEDUP_TTL", 10)

    class DummyLogger:
        def debug(self, message: str) -> None:
            dummy_logger_calls.append(message)

    monkeypatch.setattr(ai_coach_tasks, "logger", DummyLogger())

    allowed = await ai_coach_tasks._claim_plan_request("req-4", "create", attempt=0)

    assert allowed is False
    assert any("ai_plan_request_duplicate" in msg for msg in dummy_logger_calls)
