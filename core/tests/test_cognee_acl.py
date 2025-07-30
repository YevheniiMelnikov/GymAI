from types import SimpleNamespace
import pytest

from ai_coach import cognee_coach as coach


@pytest.mark.asyncio
async def test_case_success_create_and_search(monkeypatch):
    user = SimpleNamespace(id="u1")
    monkeypatch.setattr(coach.CogneeCoach, "_user", user)
    monkeypatch.setattr(coach.CogneeCoach, "_ensure_config", lambda: None)
    calls = {}

    async def fake_add(prompt, dataset_name=None, user=None):
        calls["dataset_name"] = dataset_name
        return SimpleNamespace(dataset_id="ds1", permissions=["write"])

    async def fake_cognify(datasets, user=None):
        calls["cognify"] = datasets

    async def fake_search(query, datasets, user=None, top_k=None):
        calls["search"] = datasets
        return ["ok"]

    monkeypatch.setattr(coach.cognee, "add", fake_add)
    monkeypatch.setattr(coach.cognee, "cognify", fake_cognify)
    monkeypatch.setattr(coach.cognee, "search", fake_search)

    await coach.CogneeCoach.make_request("hi")

    assert calls["dataset_name"] == f"main_dataset_{user.id}"
    assert calls["cognify"] == ["ds1"]
    assert calls["search"] == ["ds1"]


@pytest.mark.asyncio
async def test_case_conflict_existing_dataset(monkeypatch):
    user = SimpleNamespace(id="u2")
    monkeypatch.setattr(coach.CogneeCoach, "_user", user)
    monkeypatch.setattr(coach.CogneeCoach, "_ensure_config", lambda: None)
    calls = {}

    async def fake_add(prompt, dataset_name=None, user=None):
        calls.setdefault("dataset_names", []).append(dataset_name)
        if len(calls["dataset_names"]) == 1:
            raise coach.PermissionDeniedError("denied")
        return SimpleNamespace(dataset_id="ds2", permissions=["write"])

    monkeypatch.setattr(coach.cognee, "add", fake_add)
    monkeypatch.setattr(coach.cognee, "cognify", lambda datasets, user=None: None)
    monkeypatch.setattr(coach.cognee, "search", lambda *a, **k: [])

    await coach.CogneeCoach.make_request("hello")

    assert calls["dataset_names"][0] == f"main_dataset_{user.id}"
    assert calls["dataset_names"][1].startswith(f"main_dataset_{user.id}_")
    assert len(calls["dataset_names"][1]) > len(f"main_dataset_{user.id}_")
