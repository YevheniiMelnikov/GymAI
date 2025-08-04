from types import SimpleNamespace
import asyncio

import pytest

import ai_coach.cognee_coach as coach


def test_case_success_create_and_search(monkeypatch):
    async def runner():
        user = SimpleNamespace(id="u1")
        monkeypatch.setattr(coach.CogneeCoach, "_user", user)
        monkeypatch.setattr(coach.CogneeCoach, "_ensure_config", lambda: None)
        calls = {}
        cognify_calls: list[list[str]] = []

        async def fake_add(prompt, dataset_name=None, user=None):
            calls["dataset_name"] = dataset_name
            return SimpleNamespace(dataset_id="ds1", permissions=["write"])

        async def fake_cognify(datasets, user=None):
            cognify_calls.append(datasets)

        async def fake_search(query, datasets, user=None, top_k=None):
            calls["search"] = datasets
            return ["ok"]

        monkeypatch.setattr(coach.cognee, "add", fake_add)
        monkeypatch.setattr(coach.cognee, "cognify", fake_cognify)
        monkeypatch.setattr(coach.cognee, "search", fake_search)
        async def fake_contains(*a, **k):
            return False

        async def fake_add_hash(*a, **k):
            pass

        monkeypatch.setattr(coach.HashStore, "contains", fake_contains)
        monkeypatch.setattr(coach.HashStore, "add", fake_add_hash)

        res = await coach.CogneeCoach.update_client_knowledge(
            "hi", client_id=1, kind=coach.DataKind.PROMPT
        )
        assert res is None
        await asyncio.sleep(0)
        await coach.CogneeCoach.reindex(1, kind=coach.DataKind.PROMPT)
        await coach.CogneeCoach.make_request("hi", client_id=1)

        assert calls["dataset_name"] == "client_1_prompt"
        assert cognify_calls[0] == ["ds1"]
        assert cognify_calls[1] == ["client_1_prompt"]
        assert calls["search"] == ["client_1_prompt"]

    asyncio.run(runner())


def test_case_conflict_existing_dataset(monkeypatch):
    async def runner():
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
        async def fake_contains(*a, **k):
            return False

        monkeypatch.setattr(coach.HashStore, "contains", fake_contains)

        with pytest.raises(coach.PermissionDeniedError):
            await coach.CogneeCoach.update_client_knowledge(
                "hello", client_id=2, kind=coach.DataKind.PROMPT
            )

        assert calls["dataset_names"] == ["client_2_prompt"]

    asyncio.run(runner())
