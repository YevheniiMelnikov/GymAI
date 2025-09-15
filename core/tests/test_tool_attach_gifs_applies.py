import types
import asyncio
import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps
from ai_coach.agent.tools import tool_attach_gifs
from core.schemas import DayExercises, Exercise


def test_tool_attach_gifs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        class DummyGifManager:
            async def find_gif(self, name: str, mapping: dict[str, str]) -> str:
                return f"https://example.com/{name}.gif"

        async def fake_short_url(url: str) -> str:
            return url + "-s"

        cached: list[tuple[str, str]] = []

        async def fake_cache(name: str, filename: str) -> None:
            cached.append((name, filename))

        monkeypatch.setattr("ai_coach.agent.tools.get_gif_manager", lambda: DummyGifManager())
        monkeypatch.setattr("ai_coach.agent.tools.short_url", fake_short_url)
        monkeypatch.setattr("ai_coach.agent.tools.Cache.workout.cache_gif_filename", fake_cache)
        exercises = [DayExercises(day="d1", exercises=[Exercise(name="push-up", sets="1", reps="1")])]
        ctx = types.SimpleNamespace(deps=AgentDeps(client_id=1))
        result = await tool_attach_gifs(ctx, exercises)
        ex = result[0].exercises[0]
        assert ex.gif_link == "https://example.com/push-up.gif-s"
        assert cached == [("push-up", "push-up.gif")]

    asyncio.run(runner())


def test_tool_attach_gifs_no_service(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        def raise_runtime() -> None:
            raise RuntimeError("no service")

        monkeypatch.setattr("ai_coach.agent.tools.get_gif_manager", raise_runtime)
        exercises = [DayExercises(day="d1", exercises=[Exercise(name="squat", sets="1", reps="1")])]
        ctx = types.SimpleNamespace(deps=AgentDeps(client_id=1))
        result = await tool_attach_gifs(ctx, exercises)
        assert result is exercises

    asyncio.run(runner())
