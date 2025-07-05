import importlib
import sys
import types
import pytest


def load_service(monkeypatch, calls):
    dummy_cognee = types.ModuleType("cognee")

    async def add(text: str):
        calls.setdefault("add", []).append(text)

    async def cognify() -> None:
        calls["cognify"] = calls.get("cognify", 0) + 1

    async def search(query: str):
        calls.setdefault("search", []).append(query)
        return []

    dummy_cognee.add = add
    dummy_cognee.cognify = cognify
    dummy_cognee.search = search

    config_calls = {}

    def set_llm_endpoint(url: str) -> None:
        config_calls.setdefault("endpoint", []).append(url)

    def set_llm_api_key(key: str) -> None:
        config_calls.setdefault("key", []).append(key)

    def set_llm_model(model: str) -> None:
        config_calls.setdefault("model", []).append(model)

    config_obj = types.SimpleNamespace(
        set_llm_endpoint=set_llm_endpoint,
        set_llm_api_key=set_llm_api_key,
        set_llm_model=set_llm_model,
    )

    monkeypatch.setitem(sys.modules, "cognee", dummy_cognee)
    monkeypatch.setitem(sys.modules, "cognee.api", types.ModuleType("cognee.api"))
    monkeypatch.setitem(sys.modules, "cognee.api.v1", types.ModuleType("cognee.api.v1"))
    config_mod = types.ModuleType("cognee.api.v1.config")
    config_mod.config = config_obj
    monkeypatch.setitem(sys.modules, "cognee.api.v1.config", config_mod)

    module = importlib.import_module("core.ai.services.cognee_service")
    importlib.reload(module)
    CogneeService = module.CogneeService
    return CogneeService, config_calls


@pytest.mark.asyncio
async def test_configured_once(monkeypatch):
    calls: dict[str, list] = {}
    service, config_calls = load_service(monkeypatch, calls)
    monkeypatch.setattr(service, "api_url", "http://api")
    monkeypatch.setattr(service, "api_key", "secret")
    monkeypatch.setattr(service, "model", "test-model")
    service._configured = False

    await service.coach_request("hello")
    assert config_calls["endpoint"] == ["http://api"]
    assert config_calls["key"] == ["secret"]
    assert config_calls["model"] == ["test-model"]
    assert service._configured is True

    await service.coach_request("again")
    assert config_calls["endpoint"] == ["http://api"]
    assert config_calls["key"] == ["secret"]
    assert calls["add"] == ["hello", "again"]


@pytest.mark.asyncio
async def test_coach_request(monkeypatch):
    calls: dict[str, list] = {}
    service, _ = load_service(monkeypatch, calls)
    service._configured = False
    await service.coach_request("ping")

    assert calls["add"] == ["ping"]
    assert calls["cognify"] == 1
    assert calls["search"] == ["ping"]
