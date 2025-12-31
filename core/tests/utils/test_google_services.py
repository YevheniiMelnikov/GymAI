import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

from core.tests import conftest

settings_mod = sys.modules.get("config.app_settings")
if settings_mod is None:
    settings_mod = types.ModuleType("config.app_settings")
    sys.modules["config.app_settings"] = settings_mod

settings_mod.settings = types.SimpleNamespace(**conftest.settings_stub.__dict__)

services_path = Path(__file__).resolve().parents[2] / "services"

gs_spec = importlib.util.spec_from_file_location("gsheets_service", services_path / "gsheets_service.py")
if gs_spec is None:
    raise ImportError(f"Could not find module spec for gsheets_service at {services_path}")
gs_module = importlib.util.module_from_spec(gs_spec)
if gs_spec.loader is None:
    raise ImportError("Module spec has no loader")
gs_spec.loader.exec_module(gs_module)
GSheetsService = gs_module.GSheetsService

gs_store_spec = importlib.util.spec_from_file_location("gstorage_service", services_path / "gstorage_service.py")
if gs_store_spec is None:
    raise ImportError(f"Could not find module spec for gstorage_service at {services_path}")
gs_store_module = importlib.util.module_from_spec(gs_store_spec)
if gs_store_spec.loader is None:
    raise ImportError("Module spec has no loader")
gs_store_spec.loader.exec_module(gs_store_module)
ExerciseGIFStorage = gs_store_module.ExerciseGIFStorage


def test_create_new_payment_sheet(monkeypatch: Any) -> None:
    actions: dict[str, Any] = {}

    class FakeWorksheet:
        def append_row(self, row: list[str], value_input_option: str | None = None) -> None:
            actions.setdefault("header", row)

        def append_rows(self, rows: list[list[str]], value_input_option: str | None = None) -> None:
            actions["rows"] = rows

    class FakeSpreadsheet:
        def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
            actions["title"] = title
            return FakeWorksheet()

    class FakeClient:
        def open_by_key(self, key: str) -> FakeSpreadsheet:
            actions["key"] = key
            return FakeSpreadsheet()

    monkeypatch.setattr(GSheetsService, "_connect", classmethod(lambda cls: FakeClient()))
    ws = GSheetsService.create_new_payment_sheet([["a"]])
    assert actions["key"] == GSheetsService.sheet_id
    assert actions["rows"] == [["a"]]
    assert isinstance(ws, FakeWorksheet)


def test_find_gif(monkeypatch: Any) -> None:
    class FakeBucket:
        def blob(self, name: str):
            assert name == "pushup.gif"
            return FakeBlob()

    class FakeBlob:
        def generate_signed_url(self, *, expiration, version: str):
            assert version == "v4"
            return "https://signed.example/pushup.gif"

    class FakeClient:
        def bucket(self, name: str) -> FakeBucket:
            assert name == "bucket"
            return FakeBucket()

    monkeypatch.setattr("google.cloud.storage.Client", lambda: FakeClient())

    storage = ExerciseGIFStorage("bucket")

    url = storage.find_gif("pushup.gif")
    assert url == "https://signed.example/pushup.gif"
