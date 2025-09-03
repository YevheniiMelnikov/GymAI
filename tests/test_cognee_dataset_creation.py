import asyncio
from types import SimpleNamespace

from ai_coach.cognee_coach import CogneeCoach


class DummyCognee:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.added: list[str] = []

    async def create_authorized_dataset(self, name: str, user=None):  # noqa: ANN001
        self.created.append(name)

    async def add(self, text: str, dataset_name: str, user=None, node_set=None):  # noqa: ANN001
        self.added.append(dataset_name)
        return SimpleNamespace(dataset_name=dataset_name)


def test_update_dataset_creates_missing(monkeypatch) -> None:
    dummy = DummyCognee()
    monkeypatch.setattr("ai_coach.cognee_coach._c", lambda: dummy)

    class DatasetNotFoundError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass

    monkeypatch.setattr(
        "ai_coach.cognee_coach._exceptions",
        lambda: (DatasetNotFoundError, PermissionDeniedError),
    )
    monkeypatch.setattr(
        "ai_coach.hash_store.HashStore.contains",
        classmethod(lambda cls, d, h: asyncio.sleep(0, result=False)),
    )
    monkeypatch.setattr(
        "ai_coach.hash_store.HashStore.add",
        classmethod(lambda cls, d, h: asyncio.sleep(0)),
    )

    ds, created = asyncio.run(CogneeCoach.update_dataset("hello", "external_docs", None))
    assert ds == "external_docs"
    assert created is True
    assert dummy.created == ["external_docs"]
    assert dummy.added == ["external_docs"]
