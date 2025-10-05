import asyncio
from types import SimpleNamespace
from decimal import Decimal
from typing import Any

import pytest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.internal.tasks import internal_ai_coach_plan_ready
from bot.states import States
from bot.utils.ai_coach import enqueue_workout_plan_generation, enqueue_workout_plan_update
from config.app_settings import settings
from core.enums import WorkoutPlanType, WorkoutType, ProfileRole, SubscriptionPeriod
from core.schemas import Client, DayExercises, Exercise, Program, Profile, Subscription


class DummyBot:
    def __init__(self) -> None:
        self.id = 111
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class DummyRequest:
    def __init__(self, payload: dict[str, Any], bot: DummyBot, storage: MemoryStorage) -> None:
        self._payload = payload
        self.headers = {"Authorization": f"Api-Key {settings.API_KEY}"}
        self.app = {"bot": bot, "dp": SimpleNamespace(storage=storage)}

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


@pytest.mark.asyncio
async def test_enqueue_workout_plan_generation_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class DummyTask:
        @staticmethod
        def delay(payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
            captured.update(payload)

    monkeypatch.setattr("core.tasks.generate_ai_workout_plan", DummyTask)

    client = Client.model_validate(
        {
            "id": 7,
            "profile": 12,
            "credits": 0,
            "assigned_to": [],
        }
    )

    queued = await enqueue_workout_plan_generation(
        client=client,
        language="en",
        plan_type=WorkoutPlanType.PROGRAM,
        workout_type=WorkoutType.GYM,
        wishes="lean",
        request_id="req-1",
        period="4w",
        workout_days=["mon", "wed"],
    )

    assert queued is True
    assert captured["client_id"] == client.id
    assert captured["plan_type"] == WorkoutPlanType.PROGRAM.value
    assert captured["workout_days"] == ["mon", "wed"]


@pytest.mark.asyncio
async def test_enqueue_workout_plan_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class DummyTask:
        @staticmethod
        def delay(payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
            captured.update(payload)

    monkeypatch.setattr("core.tasks.update_ai_workout_plan", DummyTask)

    queued = await enqueue_workout_plan_update(
        client_id=5,
        client_profile_id=9,
        expected_workout_result="squats",
        feedback="tough",
        language="en",
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_type=WorkoutType.HOME,
        request_id="req-2",
    )

    assert queued is True
    assert captured["client_id"] == 5
    assert captured["plan_type"] == WorkoutPlanType.SUBSCRIPTION.value
    assert captured["expected_workout_result"] == "squats"


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_program(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client.model_validate(
        {
            "id": 3,
            "profile": 4,
            "credits": 0,
            "assigned_to": [],
        }
    )
    profile = Profile.model_validate(
        {
            "id": 4,
            "role": ProfileRole.client,
            "tg_id": 100,
            "language": "en",
        }
    )
    program = Program(
        id=1,
        client_profile=client.profile,
        exercises_by_day=[DayExercises(day="1", exercises=[Exercise(name="push-up", sets="3", reps="10")])],
        created_at=0.0,
        split_number=1,
        workout_type="gym",
        wishes="",
    )

    async def fake_get_client(_: int) -> Client:
        return client

    async def fake_get_profile(_: int) -> Profile | None:
        return profile

    saved_cache: dict[str, Any] = {}
    saved_args: dict[str, Any] = {}

    async def fake_save_program(
        client_profile_id: int,
        exercises: list[DayExercises],
        split_number: int,
        wishes: str,
    ) -> Program:
        saved_args.update(
            {
                "client_profile_id": client_profile_id,
                "split_number": split_number,
                "wishes": wishes,
            }
        )
        return program

    async def fake_cache_save_program(client_profile_id: int, data: dict[str, Any]) -> None:
        saved_cache.update({"client_profile_id": client_profile_id, "data": data})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.client.get_client", fake_get_client)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.save_program", fake_save_program)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.save_program", fake_cache_save_program)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.msg_text",
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
    monkeypatch.setattr("bot.handlers.internal.tasks.get_redis_client", lambda: dummy_redis)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "client_id": client.id,
            "plan_type": WorkoutPlanType.PROGRAM.value,
            "status": "success",
            "action": "create",
            "plan": program.model_dump(mode="json"),
        },
        bot,
        storage,
    )

    response = await internal_ai_coach_plan_ready(request)
    assert response.status == 200
    assert saved_args["client_profile_id"] == client.profile
    assert saved_cache["client_profile_id"] == client.profile
    assert bot.sent[0]["text"] == "new_program:en"
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    assert await storage.get_state(key) == States.program_view.state
    data = await storage.get_data(key)
    assert len(data["exercises"]) == 1
    assert data["last_request_id"] == ""


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_update(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client.model_validate(
        {
            "id": 6,
            "profile": 7,
            "credits": 0,
            "assigned_to": [],
        }
    )
    profile = Profile.model_validate(
        {
            "id": 7,
            "role": ProfileRole.client,
            "tg_id": 101,
            "language": "en",
        }
    )
    updated_subscription = Subscription(
        id=9,
        client_profile=client.profile,
        enabled=True,
        price=0,
        workout_type="gym",
        wishes="",
        period="1m",
        workout_days=["mon"],
        exercises=[DayExercises(day="1", exercises=[Exercise(name="squat", sets="3", reps="12")])],
        payment_date="2024-01-01",
    )

    existing_subscription = Subscription(
        id=9,
        client_profile=client.profile,
        enabled=True,
        price=0,
        workout_type="gym",
        wishes="",
        period="1m",
        workout_days=["mon"],
        exercises=[DayExercises(day="1", exercises=[Exercise(name="old", sets="3", reps="8")])],
        payment_date="2024-01-01",
    )

    async def fake_get_client(_: int) -> Client:
        return client

    async def fake_get_profile(_: int) -> Profile | None:
        return profile

    async def fake_get_subscription(_: int) -> Subscription:
        return existing_subscription

    updated_payload: dict[str, Any] = {}
    cache_updates: dict[str, Any] = {}

    async def fake_update_subscription(sub_id: int, data: dict[str, Any]) -> None:
        updated_payload.update({"id": sub_id, "data": data})

    async def fake_cache_update(_: int, data: dict[str, Any]) -> None:
        cache_updates.update(data)

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.client.get_client", fake_get_client)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.get_latest_subscription", fake_get_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.update_subscription", fake_update_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.update_subscription", fake_cache_update)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.msg_text",
        lambda key, lang: f"{key}:{lang}",
    )
    dummy_redis = DummyRedis()
    monkeypatch.setattr("bot.handlers.internal.tasks.get_redis_client", lambda: dummy_redis)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "client_id": client.id,
            "plan_type": WorkoutPlanType.SUBSCRIPTION.value,
            "status": "success",
            "action": "update",
            "plan": updated_subscription.model_dump(mode="json"),
        },
        bot,
        storage,
    )

    response = await internal_ai_coach_plan_ready(request)
    assert response.status == 200
    assert updated_payload["id"] == existing_subscription.id
    assert cache_updates["client_profile"] == client.profile
    assert bot.sent[0]["text"] == "program_updated:en"
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    assert await storage.get_state(key) == States.program_view.state
    data = await storage.get_data(key)
    assert len(data["exercises"]) == 1
    assert data["last_request_id"] == ""


@pytest.mark.asyncio
async def test_internal_ai_plan_ready_subscription_create(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client.model_validate(
        {
            "id": 10,
            "profile": 11,
            "credits": 0,
            "assigned_to": [],
        }
    )
    profile = Profile.model_validate(
        {
            "id": 11,
            "role": ProfileRole.client,
            "tg_id": 103,
            "language": "en",
        }
    )
    new_subscription = Subscription(
        id=0,
        client_profile=client.profile,
        enabled=True,
        price=450,
        workout_type="gym",
        wishes="lean",
        period=SubscriptionPeriod.one_month.value,
        workout_days=["mon", "wed"],
        exercises=[DayExercises(day="1", exercises=[Exercise(name="lunge", sets="3", reps="12")])],
        payment_date="2024-01-01",
    )

    async def fake_get_client(_: int) -> Client:
        return client

    async def fake_get_profile(_: int) -> Profile | None:
        return profile

    created_payload: dict[str, Any] = {}

    async def fake_create_subscription(
        client_profile_id: int,
        workout_days: list[str],
        wishes: str,
        amount: Decimal,
        period: SubscriptionPeriod,
        exercises: list[dict[str, Any]],
    ) -> int | None:
        created_payload.update(
            {
                "client_profile_id": client_profile_id,
                "workout_days": workout_days,
                "wishes": wishes,
                "amount": amount,
                "period": period,
                "exercises": exercises,
            }
        )
        return 42

    saved_subscription: dict[str, Any] = {}

    async def fake_cache_save_subscription(client_profile_id: int, data: dict[str, Any]) -> None:
        saved_subscription.update({"client_profile_id": client_profile_id, "data": data})

    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.client.get_client", fake_get_client)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.profile.get_profile", fake_get_profile)
    monkeypatch.setattr("bot.handlers.internal.tasks.APIService.workout.create_subscription", fake_create_subscription)
    monkeypatch.setattr("bot.handlers.internal.tasks.Cache.workout.save_subscription", fake_cache_save_subscription)
    monkeypatch.setattr(
        "bot.handlers.internal.tasks.msg_text",
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
    monkeypatch.setattr("bot.handlers.internal.tasks.get_redis_client", lambda: dummy_redis)

    bot = DummyBot()
    storage = MemoryStorage()
    request = DummyRequest(
        {
            "client_id": client.id,
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
    assert response.status == 200
    assert created_payload["client_profile_id"] == client.profile
    assert saved_subscription["client_profile_id"] == client.profile
    assert saved_subscription["data"]["id"] == 42
    assert bot.sent[0]["text"] == "new_program:en"
    key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    assert await storage.get_state(key) == States.program_view.state
    data = await storage.get_data(key)
    assert data["subscription"] is True
    assert data["last_request_id"] == "req-sub"
