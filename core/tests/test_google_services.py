import importlib.util
from pathlib import Path
from typing import Any

services_path = Path(__file__).resolve().parents[1] / "services"

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
    import asyncio

    stored: dict[str, str] = {}

    class FakeBlob:
        name = "pushup.gif"

        def exists(self) -> bool:
            return True

    class FakeBucket:
        def list_blobs(
            self, prefix: str | None = None, max_results: int | None = None
        ) -> list[FakeBlob]:
            return [FakeBlob()]

    class FakeClient:
        def bucket(self, name: str) -> FakeBucket:
            assert name == "bucket"
            return FakeBucket()

    monkeypatch.setattr("google.cloud.storage.Client", lambda: FakeClient())

    storage = ExerciseGIFStorage("bucket")

    async def fake_get(name: str) -> None:
        return None

    async def fake_cache(name: str, value: str) -> None:
        stored[name] = value

    monkeypatch.setattr(gs_store_module.Cache.workout, "get_exercise_gif", fake_get)
    monkeypatch.setattr(gs_store_module.Cache.workout, "cache_gif_filename", fake_cache)

    url = asyncio.run(storage.find_gif("Push Up", {"pushup": ["Push Up"]}))
    assert url == "https://storage.googleapis.com/bucket/pushup.gif"
    assert stored["push up"] == "pushup.gif"
