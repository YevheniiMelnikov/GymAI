import pytest
from types import SimpleNamespace

from core.ai_coach.cognee_coach import CogneeCoach
from core.ai_coach.utils import init_ai_coach, coach_ready_event

@pytest.mark.asyncio
async def test_reinit_on_failure(monkeypatch):
    called = 0
    async def broken(*args, **kwargs):
        nonlocal called
        called += 1
        if called == 1:
            raise RuntimeError("boom")
    monkeypatch.setattr(CogneeCoach, "_ensure_config", broken)
    monkeypatch.setattr(CogneeCoach, "_user", None)
    async def fake_user():
        return SimpleNamespace(id="test")
    monkeypatch.setattr("core.ai_coach.cognee_coach.get_default_user", fake_user)
    if coach_ready_event is not None:
        coach_ready_event.clear()
    with pytest.raises(RuntimeError):
        await init_ai_coach(CogneeCoach)

    async def ok(*args, **kwargs):
        pass
    monkeypatch.setattr(CogneeCoach, "_ensure_config", ok)
    await init_ai_coach(CogneeCoach)
    assert CogneeCoach._user is not None
