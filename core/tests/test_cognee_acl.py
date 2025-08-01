from types import SimpleNamespace
import pytest

import ai_coach.cognee_coach as coach


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

    await coach.CogneeCoach.save_prompt("hi")
    await coach.CogneeCoach.make_request("hi")

    assert calls["dataset_name"] == f"main_{user.id}"
    assert calls["cognify"] == ["ds1"]
    assert calls["search"] == [f"main_{user.id}"]


@pytest.mark.asyncio
async def test_case_conflict_existing_dataset(monkeypatch):
    user = SimpleNamespace(id="u2")
    monkeypatch.setattr(coach.CogneeCoach, "_user", user)
    monkeypatch.setattr(coach.CogneeCoach, "_ensure_config", lambda: None)
    calls = {}

    async def fake_add(prompt, dataset_name=None, user=None):
        calls.setdefault("dataset_names", []).append(dataset_name)
        raise coach.PermissionDeniedError("denied")

    monkeypatch.setattr(coach.cognee, "add", fake_add)
    monkeypatch.setattr(coach.cognee, "cognify", lambda datasets, user=None: None)
    monkeypatch.setattr(coach.cognee, "search", lambda *a, **k: [])

    with pytest.raises(coach.PermissionDeniedError):
        await coach.CogneeCoach.save_prompt("hello")

    assert calls["dataset_names"] == [f"main_{user.id}"]

