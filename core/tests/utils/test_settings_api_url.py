import os

import importlib.util
from pathlib import Path


import pytest

import conftest


def _patched_base_settings_init(self: object, **data: object) -> None:
    for name, value in self.__class__.__dict__.items():
        if name.startswith("_") or callable(value) or isinstance(value, property):
            continue
        setattr(self, name, value)
    for key, value in data.items():
        setattr(self, key, value)


_original_base_settings_init = conftest.BaseSettings.__init__
conftest.BaseSettings.__init__ = _patched_base_settings_init
spec = importlib.util.spec_from_file_location(
    "app_settings", Path(__file__).resolve().parents[3] / "config" / "app_settings.py"
)
assert spec is not None and spec.loader is not None
app_settings_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_settings_module)
conftest.BaseSettings.__init__ = _original_base_settings_init
Settings = app_settings_module.Settings


def _build_settings(api_host: str, host_port: str, internal_port: str) -> Settings:
    instance: Settings = Settings.__new__(Settings)
    instance.API_HOST = api_host
    instance.HOST_API_PORT = host_port
    instance.API_INTERNAL_PORT = internal_port
    return instance


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    env_names: tuple[str, ...] = (
        "API_URL",
        "API_HOST",
        "API_PORT",
        "API_SERVICE_HOST",
        "KUBERNETES_SERVICE_HOST",
    )
    for name in env_names:
        monkeypatch.delenv(name, raising=False)


def _set_docker_presence(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    def fake_exists(path: str) -> bool:
        target: str = "/.dockerenv"
        return present and path == target

    monkeypatch.setattr(os.path, "exists", fake_exists)


@pytest.mark.parametrize("present", [False, True])
def test_api_url_loopback_host(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    _clear_env(monkeypatch)
    _set_docker_presence(monkeypatch, present)
    settings_obj: Settings = _build_settings("http://127.0.0.1", "18000", "8000")
    result: str = settings_obj._derive_api_url(present)
    expected: str = "http://api:8000/" if present else "http://127.0.0.1:18000/"
    assert result == expected


def test_api_url_keeps_existing_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _set_docker_presence(monkeypatch, True)
    settings_obj: Settings = _build_settings("http://backend:9000", "8000", "8100")
    result: str = settings_obj._derive_api_url(True)
    assert result == "http://backend:9000/"


def test_api_url_prefers_env_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _set_docker_presence(monkeypatch, True)
    monkeypatch.setenv("API_PORT", "9100")
    settings_obj: Settings = _build_settings("http://backend", "8000", "8100")
    result: str = settings_obj._derive_api_url(True)
    assert result == "http://backend:9100/"
