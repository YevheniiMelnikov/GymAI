import asyncio
from types import SimpleNamespace

from ai_coach.cognee_coach import CogneeCoach
import ai_coach.cognee_coach as coach


def test_update_dataset_ensures_exists(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def ensure(cls, name: str, user: object) -> None:  # type: ignore[override]
        calls.append(("ensure", name))

    async def fake_add(*, text: str, dataset_name: str, user: object, node_set: list[str] | None):
        calls.append(("add", dataset_name))
        return SimpleNamespace(dataset_id=dataset_name)

    monkeypatch.setattr(CogneeCoach, "_ensure_dataset_exists", classmethod(ensure))
    monkeypatch.setattr(coach, "_safe_add", fake_add)

    async def runner() -> None:
        ds, created = await CogneeCoach.update_dataset("x", "ds", user=None)
        assert (ds, created) == ("ds", True)

    asyncio.run(runner())
    assert calls == [("ensure", "ds"), ("add", "ds")]
