from types import SimpleNamespace
import pytest

from core.ai_coach import cognee_coach as coach


@pytest.mark.asyncio
async def test_case_success_create_and_search(monkeypatch):
    user = SimpleNamespace(id="u1")
    monkeypatch.setattr(coach, "_COGNEE_USER", user)
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
    monkeypatch.setattr(coach.cognee, "share_dataset", lambda *a, **k: None)
    monkeypatch.setenv("ENABLE_BACKEND_ACCESS_CONTROL", "True")

    await coach.CogneeCoach.coach_request("hi")

    assert calls["dataset_name"] == f"main_dataset_{user.id}"
    assert calls["cognify"] == ["ds1"]
    assert calls["search"] == ["ds1"]


@pytest.mark.asyncio
async def test_case_conflict_existing_dataset(monkeypatch):
    user = SimpleNamespace(id="u2")
    monkeypatch.setattr(coach, "_COGNEE_USER", user)
    calls = {}

    async def fake_add(prompt, dataset_name=None, user=None):
        return SimpleNamespace(dataset_id="ds2", permissions=["read"])

    async def fake_share(dataset_id, principal_id, permissions):
        calls["share"] = (dataset_id, principal_id, permissions)

    monkeypatch.setattr(coach.cognee, "add", fake_add)
    monkeypatch.setattr(coach.cognee, "share_dataset", fake_share)
    monkeypatch.setattr(coach.cognee, "cognify", lambda datasets, user=None: None)
    monkeypatch.setattr(coach.cognee, "search", lambda *a, **k: [])
    monkeypatch.setenv("ENABLE_BACKEND_ACCESS_CONTROL", "True")

    await coach.CogneeCoach.coach_request("hello")

    assert calls["share"] == ("ds2", user.id, ["write"])
