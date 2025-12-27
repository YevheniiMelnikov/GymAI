import pytest  # pyrefly: ignore[import-error]

import asyncio

from ai_coach.api import DISPATCH
from ai_coach.agent import CoachAgent
import ai_coach.api as coach_api
from ai_coach.types import CoachMode
from core.schemas import Program, Subscription
from core.enums import WorkoutPlanType, WorkoutLocation


def _patch_agent(monkeypatch: pytest.MonkeyPatch, attr: str, value) -> None:
    monkeypatch.setattr(CoachAgent, attr, value)
    monkeypatch.setattr(coach_api.CoachAgent, attr, value)


def test_program_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        captured: dict[str, tuple] = {}

        async def fake_generate(
            prompt: str | None,
            deps: object,
            *,
            workout_location: WorkoutLocation | None = None,
            **kwargs: object,
        ) -> str:
            captured["args"] = (prompt, deps, workout_location, kwargs)
            return "program-result"

        _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
        ctx = {
            "prompt": "p",
            "deps": "d",
            "wishes": "w",
            "workout_location": WorkoutLocation.HOME,
            "instructions": "i",
        }
        result = await DISPATCH[CoachMode.program](ctx)  # pyrefly: ignore[bad-argument-type]
        assert result == "program-result"
        assert captured["args"] == (
            "p",
            "d",
            WorkoutLocation.HOME,
            {"wishes": "w", "instructions": "i", "output_type": Program, "profile_context": None},
        )

    asyncio.run(runner())


def test_subscription_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        captured: dict[str, tuple] = {}

        async def fake_generate(
            prompt: str | None,
            deps: object,
            *,
            workout_location: WorkoutLocation | None = None,
            **kwargs: object,
        ) -> str:
            captured["args"] = (prompt, deps, workout_location, kwargs)
            return "subscription-result"

        _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
        ctx = {
            "prompt": "p",
            "period": "1m",
            "split_number": 1,
            "deps": "d",
            "wishes": "w",
            "workout_location": WorkoutLocation.HOME,
            "instructions": "i",
        }
        result = await DISPATCH[CoachMode.subscription](ctx)  # pyrefly: ignore[bad-argument-type]
        assert result == "subscription-result"
        assert captured["args"] == (
            "p",
            "d",
            WorkoutLocation.HOME,
            {
                "period": "1m",
                "split_number": 1,
                "wishes": "w",
                "instructions": "i",
                "output_type": Subscription,
                "profile_context": None,
            },
        )

    asyncio.run(runner())


def test_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        captured: dict[str, tuple] = {}

        async def fake_update(
            prompt: str | None,
            expected_workout: str,
            feedback: str,
            *,
            workout_location: WorkoutLocation | None = None,
            deps: object | None = None,
            output_type: type[Program] | None = None,
            instructions: str | None = None,
            profile_context: str | None = None,
        ) -> str:
            captured["args"] = (
                prompt,
                expected_workout,
                feedback,
                workout_location,
                deps,
                output_type,
                instructions,
                profile_context,
            )
            return "update-result"

        _patch_agent(monkeypatch, "update_workout_plan", staticmethod(fake_update))
        ctx = {
            "prompt": "p",
            "expected_workout": "ew",
            "feedback": "fb",
            "deps": "d",
            "wishes": "",
            "workout_location": WorkoutLocation.HOME,
            "plan_type": WorkoutPlanType.PROGRAM,
            "instructions": "i",
        }
        result = await DISPATCH[CoachMode.update](ctx)  # pyrefly: ignore[bad-argument-type]
        assert result == "update-result"
        assert captured["args"] == ("p", "ew", "fb", WorkoutLocation.HOME, "d", Program, "i", None)

    asyncio.run(runner())


def test_ask_ai_dispatch_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        captured: dict[str, tuple] = {}

        async def fake_answer(prompt: str, deps: object) -> str:
            captured["args"] = (prompt, deps)
            return "ask_ai-result"

        _patch_agent(monkeypatch, "answer_question", staticmethod(fake_answer))
        ctx = {"prompt": "p", "deps": "d"}
        result = await DISPATCH[CoachMode.ask_ai](ctx)  # pyrefly: ignore[bad-argument-type]
        assert result == "ask_ai-result"
        assert captured["args"] == ("p", "d")
        assert set(DISPATCH) == {
            CoachMode.program,
            CoachMode.subscription,
            CoachMode.update,
            CoachMode.ask_ai,
            CoachMode.diet,
        }

    asyncio.run(runner())
