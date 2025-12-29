import asyncio
from types import SimpleNamespace
from decimal import Decimal
from typing import Any

import pytest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.internal.tasks import internal_ai_coach_plan_ready, _resolve_profile
from core.ai_coach.state.plan import AiPlanState
from bot.utils.ai_coach import enqueue_workout_plan_generation, enqueue_workout_plan_update
from config.app_settings import settings
from core.enums import WorkoutPlanType, WorkoutLocation, SubscriptionPeriod
from core.exceptions import ProfileNotFoundError
from core.schemas import DayExercises, Exercise, Program, Profile, Subscription


def _make_profile(profile_id: int) -> Profile:
    return Profile.model_validate({"id": profile_id, "tg_id": profile_id, "language": "en", "credits": 0})


class DummyBot:
    def __init__(self) -> None:
        self.id = 111
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


settings.INTERNAL_API_KEY = "test-internal-key"
settings.DEBUG = False


class DummyRequest:
    def __init__(self, payload: dict[str, Any], bot: DummyBot, storage: MemoryStorage) -> None:
        self._payload = payload
        self.headers = {"X-Internal-Api-Key": settings.INTERNAL_API_KEY or ""}
        self.app = {"bot": bot, "dp": SimpleNamespace(storage=storage)}
        self.transport = SimpleNamespace(get_extra_info=lambda name: ("127.0.0.1", 8080))

    async def json(self) -> dict[str, Any]:
        await asyncio.sleep(0)
        return self._payload


class DummyRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


@pytest.mark.asyncio
async def test_resolve_profile_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_record = _make_profile(1)

    calls: list[int] = []

    async def fake_get_profile(profile_id: int, *, use_fallback: bool = True) -> Profile:
        calls.append(profile_id)
        return profile_record

    async def fail_get_profile(_: int) -> Profile | None:
        raise AssertionError("should not call profile lookup")

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", fake_get_profile)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.APIService.profile.get_profile",
        fail_get_profile,
    )
    resolved = await _resolve_profile(profile_record.id, profile_record.id)
    assert resolved == profile_record
    assert calls == [profile_record.id]


@pytest.mark.asyncio
async def test_resolve_profile_fetches_when_cache_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_record = _make_profile(3)

    async def missing_cache(_: int, *, use_fallback: bool = True) -> Profile:
        raise ProfileNotFoundError(4)

    async def fetch_by_profile(profile_id: int) -> Profile | None:
        assert profile_id == profile_record.id
        return profile_record

    saved: dict[str, Any] = {}

    async def save_profile(profile_id: int, payload: dict[str, Any]) -> None:
        saved.update({"profile_id": profile_id, "payload": payload})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", missing_cache)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.APIService.profile.get_profile",
        fetch_by_profile,
    )
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.save_record", save_profile)

    resolved = await _resolve_profile(profile_record.id, profile_record.id)
    assert resolved == profile_record
    assert saved["profile_id"] == profile_record.id


@pytest.mark.asyncio
async def test_resolve_profile_without_profile_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_record = _make_profile(6)

    async def fail_cache(_: int, *, use_fallback: bool = True) -> Profile:
        raise AssertionError("cache should not be used without profile id")

    async def fetch_profile_by_id(profile_id: int) -> Profile | None:
        assert profile_id == profile_record.id
        return profile_record

    saved: dict[str, Any] = {}

    async def save_profile(profile_id: int, payload: dict[str, Any]) -> None:
        saved.update({"profile_id": profile_id, "payload": payload})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", fail_cache)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fetch_profile_by_id)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.APIService.profile.get_profile",
        fetch_profile_by_id,
    )
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.save_record", save_profile)

    resolved = await _resolve_profile(profile_record.id, None)
    assert resolved == profile_record
    assert saved["profile_id"] == profile_record.id


@pytest.mark.asyncio
async def test_enqueue_workout_plan_generation_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class DummyResult:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.id = "dummy-id"
            self.payload = payload

    class DummyTask:
        @staticmethod
        def apply_async(
            *,
            args: tuple[dict[str, Any]],
            queue: str,
            routing_key: str,
            headers: dict[str, Any],
        ) -> DummyResult:
            assert queue == "ai_coach"
            assert routing_key == "ai_coach"
            assert headers["plan_type"] == WorkoutPlanType.PROGRAM.value
            payload = args[0]
            captured.update(payload)
            return DummyResult(payload)

    monkeypatch.setattr("bot.utils.ai_coach.generate_ai_workout_plan", DummyTask)

    profile_record = _make_profile(7)

    queued = await enqueue_workout_plan_generation(
        profile=profile_record,
        plan_type=WorkoutPlanType.PROGRAM,
        workout_location=WorkoutLocation.GYM,
        wishes="lean",
        request_id="req-1",
        period="4w",
        split_number=2,
    )

    assert queued is True
    assert captured["profile_id"] == profile_record.id
    assert captured["plan_type"] == WorkoutPlanType.PROGRAM.value
    assert captured["split_number"] == 2


@pytest.mark.asyncio
async def test_enqueue_workout_plan_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class DummyResult:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.id = "dummy-id"
            self.payload = payload

    class DummyTask:
        @staticmethod
        def apply_async(
            *,
            args: tuple[dict[str, Any]],
            queue: str,
            routing_key: str,
            headers: dict[str, Any],
        ) -> DummyResult:
            assert queue == "ai_coach"
            assert routing_key == "ai_coach"
            assert headers["plan_type"] == WorkoutPlanType.SUBSCRIPTION.value
            payload = args[0]
            captured.update(payload)
            return DummyResult(payload)

    monkeypatch.setattr("bot.utils.ai_coach.update_ai_workout_plan", DummyTask)

    queued = await enqueue_workout_plan_update(
        profile_id=9,
        feedback="tough",
        language="en",
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_location=WorkoutLocation.HOME,
        request_id="req-2",
    )

    assert queued is True
    assert captured["profile_id"] == 9
    assert captured["plan_type"] == WorkoutPlanType.SUBSCRIPTION.value
    assert captured["feedback"] == "tough"


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    profile_record = _make_profile(3)
    profile = Profile.model_validate(
        {
            "id": 4,
            "tg_id": profile_record.tg_id,
            "language": "en",
        }
    )
    program = Program(
        id=1,
        profile=profile_record.id,
        exercises_by_day=[DayExercises(day="1", exercises=[Exercise(name="push-up", sets="3", reps="10")])],
        created_at=0.0,
        split_number=1,
        workout_location="gym",
        wishes="",
    )

    cache_calls: list[int] = []

    async def fake_get_cached_profile(profile_id: int, *, use_fallback: bool = True) -> Profile:
        cache_calls.append(profile_id)
        return profile_record

    async def fake_cache_save_profile(*_: Any, **__: Any) -> None:
        return None

    async def fake_get_profile_service(_: int) -> Profile | None:
        return profile

    saved_cache: dict[str, Any] = {}
    saved_args: dict[str, Any] = {}

    async def fake_save_program(
        profile_id: int,
        exercises: list[DayExercises],
        split_number: int,
        wishes: str,
    ) -> Program:
        saved_args.update(
            {
                "profile_id": profile_id,
                "split_number": split_number,
                "wishes": wishes,
            }
        )
        return program

    async def fake_cache_save_program(profile_id: int, data: dict[str, Any]) -> None:
        saved_cache.update({"profile_id": profile_id, "data": data})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", fake_get_cached_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.save_record", fake_cache_save_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile_service)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.save_program", fake_save_program)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.save_program", fake_cache_save_program)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.translate",
        lambda key, lang: f"{key}:{lang}",
    )
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.program_view_kb",
        lambda lang, url: {"kb": lang, "url": url},
    )
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.get_webapp_url",
        lambda name: f"url:{name}",
    )
    dummy_redis = DummyRedis()
    monkeypatch.setattr("bot.handlers.internal.tasks.AiPlanState.create", lambda: AiPlanState(dummy_redis))
    scheduled: list[asyncio.Task[Any]] = []
    original_create_task = asyncio.create_task

    def capture_task(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        task = original_create_task(coro, name=name)
        scheduled.append(task)
        return task

    monkeypatch.setattr("bot.handlers.internal.tasks.asyncio.create_task", capture_task)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "profile_id": profile_record.id,
            "plan_type": WorkoutPlanType.PROGRAM.value,
            "status": "success",
            "action": "create",
            "request_id": "req-program",
            "plan": program.model_dump(mode="json"),
        },
        bot,
        storage,
    )

    response = await internal_ai_coach_plan_ready(request)
    if scheduled:
        await asyncio.gather(*scheduled)
    assert response.status == 202
    assert cache_calls == [profile_record.id]
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    data = await storage.get_data(key)
    assert len(data["exercises"]) == 1
    assert data["last_request_id"] == "req-program"


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    profile_record = _make_profile(6)
    profile = Profile.model_validate(
        {
            "id": 7,
            "tg_id": profile_record.tg_id,
            "language": "en",
        }
    )
    updated_subscription = Subscription(
        id=9,
        profile=profile_record.id,
        enabled=True,
        price=0,
        workout_location="gym",
        wishes="",
        period="1m",
        split_number=1,
        exercises=[DayExercises(day="1", exercises=[Exercise(name="squat", sets="3", reps="12")])],
        payment_date="2024-01-01",
    )

    existing_subscription = Subscription(
        id=9,
        profile=profile_record.id,
        enabled=True,
        price=0,
        workout_location="gym",
        wishes="",
        period="1m",
        split_number=1,
        exercises=[DayExercises(day="1", exercises=[Exercise(name="old", sets="3", reps="8")])],
        payment_date="2024-01-01",
    )

    cache_calls: list[int] = []

    async def fake_get_cached_profile(profile_id: int, *, use_fallback: bool = True) -> Profile:
        cache_calls.append(profile_id)
        return profile_record

    async def fake_get_profile_service(_: int) -> Profile | None:
        return profile

    async def fake_get_subscription(_: int) -> Subscription:
        return existing_subscription

    updated_payload: dict[str, Any] = {}
    cache_updates: dict[str, Any] = {}

    async def fake_cache_save_profile(*_: Any, **__: Any) -> None:
        return None

    async def fake_update_subscription(sub_id: int, data: dict[str, Any]) -> None:
        updated_payload.update({"id": sub_id, "data": data})

    async def fake_cache_update(_: int, data: dict[str, Any]) -> None:
        cache_updates.update(data)

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", fake_get_cached_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.save_record", fake_cache_save_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile_service)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.get_latest_subscription", fake_get_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.update_subscription", fake_update_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.update_subscription", fake_cache_update)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.translate",
        lambda key, lang: f"{key}:{lang}",
    )
    dummy_redis = DummyRedis()
    monkeypatch.setattr("bot.handlers.internal.tasks.AiPlanState.create", lambda: AiPlanState(dummy_redis))
    scheduled: list[asyncio.Task[Any]] = []
    original_create_task = asyncio.create_task

    def capture_task(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        task = original_create_task(coro, name=name)
        scheduled.append(task)
        return task

    monkeypatch.setattr("bot.handlers.internal.tasks.asyncio.create_task", capture_task)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "profile_id": profile_record.id,
            "plan_type": WorkoutPlanType.SUBSCRIPTION.value,
            "status": "success",
            "action": "update",
            "request_id": "req-update",
            "plan": updated_subscription.model_dump(mode="json"),
        },
        bot,
        storage,
    )

    response = await internal_ai_coach_plan_ready(request)
    if scheduled:
        await asyncio.gather(*scheduled)
    assert response.status == 202
    assert cache_calls == [profile_record.id]
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    data = await storage.get_data(key)
    assert len(data["exercises"]) == 1
    assert data["last_request_id"] == "req-update"


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_subscription_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    profile_record = _make_profile(10)
    profile = Profile.model_validate(
        {
            "id": 11,
            "tg_id": profile_record.tg_id,
            "language": "en",
        }
    )
    new_subscription = Subscription(
        id=0,
        profile=profile_record.id,
        enabled=True,
        price=450,
        workout_location="gym",
        wishes="lean",
        period=SubscriptionPeriod.one_month.value,
        split_number=2,
        exercises=[DayExercises(day="1", exercises=[Exercise(name="lunge", sets="3", reps="12")])],
        payment_date="2024-01-01",
    )

    cache_calls: list[int] = []

    async def fake_get_cached_profile(profile_id: int, *, use_fallback: bool = True) -> Profile:
        cache_calls.append(profile_id)
        return profile_record

    async def fake_get_profile_service(_: int) -> Profile | None:
        return profile

    created_payload: dict[str, Any] = {}

    async def fake_cache_save_profile(*_: Any, **__: Any) -> None:
        return None

    async def fake_create_subscription(
        profile_id: int,
        split_number: int,
        wishes: str,
        amount: Decimal,
        period: SubscriptionPeriod,
        workout_location: str,
        exercises: list[dict[str, Any]],
    ) -> int | None:
        created_payload.update(
            {
                "profile_id": profile_id,
                "split_number": split_number,
                "wishes": wishes,
                "amount": amount,
                "period": period,
                "workout_location": workout_location,
                "exercises": exercises,
            }
        )
        return 42

    saved_subscription: dict[str, Any] = {}

    async def fake_cache_save_subscription(profile_id: int, data: dict[str, Any]) -> None:
        saved_subscription.update({"profile_id": profile_id, "data": data})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.get_record", fake_get_cached_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.profile.save_record", fake_cache_save_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile_service)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.create_subscription", fake_create_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.save_subscription", fake_cache_save_subscription)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.translate",
        lambda key, lang: f"{key}:{lang}",
    )
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.program_view_kb",
        lambda lang, url: {"kb": lang, "url": url},
    )
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.get_webapp_url",
        lambda name, _lang=None: f"url:{name}",
    )
    dummy_redis = DummyRedis()
    monkeypatch.setattr("bot.handlers.internal.tasks.AiPlanState.create", lambda: AiPlanState(dummy_redis))
    scheduled: list[asyncio.Task[Any]] = []
    original_create_task = asyncio.create_task

    def capture_task(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        task = original_create_task(coro, name=name)
        scheduled.append(task)
        return task

    monkeypatch.setattr("bot.handlers.internal.tasks.asyncio.create_task", capture_task)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "profile_id": profile_record.id,
            "plan_type": WorkoutPlanType.SUBSCRIPTION.value,
            "status": "success",
            "action": "create",
            "request_id": "req-sub",
            "plan": new_subscription.model_dump(mode="json"),
        },
        bot,
        storage,
    )

    response = await internal_ai_coach_plan_ready(request)
    if scheduled:
        await asyncio.gather(*scheduled)
    assert response.status == 202
    assert cache_calls == [profile_record.id]
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    data = await storage.get_data(key)
    assert data["subscription"] is True
    assert data["last_request_id"] == "req-sub"
