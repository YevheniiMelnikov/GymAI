import pytest
import importlib.util
from pathlib import Path
import sys
import types

services_path = Path(__file__).resolve().parents[1] / "services" / "outer"

dummy_cache = types.ModuleType("core.cache")
dummy_cache.Cache = types.SimpleNamespace(
    workout=types.SimpleNamespace(get_exercise_gif=None, cache_gif_filename=None)
)
sys.modules["core.cache"] = dummy_cache

gs_spec = importlib.util.spec_from_file_location(
    "gsheets_service", services_path / "gsheets_service.py"
)
gs_module = importlib.util.module_from_spec(gs_spec)
gs_spec.loader.exec_module(gs_module)  # type: ignore[arg-type]
GSheetsService = gs_module.GSheetsService

gs_store_spec = importlib.util.spec_from_file_location(
    "gstorage_service", services_path / "gstorage_service.py"
)
gs_store_module = importlib.util.module_from_spec(gs_store_spec)
gs_store_spec.loader.exec_module(gs_store_module)  # type: ignore[arg-type]
ExerciseGIFStorage = gs_store_module.ExerciseGIFStorage


def test_create_new_payment_sheet(monkeypatch):
    actions = {}

    class FakeWorksheet:
        def append_row(self, row, value_input_option=None):
            actions.setdefault('header', row)
        def append_rows(self, rows, value_input_option=None):
            actions['rows'] = rows

    class FakeSpreadsheet:
        def add_worksheet(self, title, rows, cols):
            actions['title'] = title
            return FakeWorksheet()

    class FakeClient:
        def open_by_key(self, key):
            actions['key'] = key
            return FakeSpreadsheet()

    monkeypatch.setattr(GSheetsService, '_connect', classmethod(lambda cls: FakeClient()))
    ws = GSheetsService.create_new_payment_sheet([["a"]])
    assert actions['key'] == GSheetsService.sheet_id
    assert actions['rows'] == [["a"]]
    assert isinstance(ws, FakeWorksheet)


def test_find_gif(monkeypatch):
    import asyncio
    stored = {}

    class FakeBlob:
        name = 'pushup.gif'
        def exists(self):
            return True
    class FakeBucket:
        def list_blobs(self, prefix=None):
            return [FakeBlob()]

    class FakeClient:
        def bucket(self, name):
            assert name == 'bucket'
            return FakeBucket()

    monkeypatch.setattr('google.cloud.storage.Client', lambda: FakeClient())

    storage = ExerciseGIFStorage('bucket')

    async def fake_get(name):
        return None
    async def fake_cache(name, value):
        stored[name] = value

    monkeypatch.setattr(gs_store_module.Cache.workout, 'get_exercise_gif', fake_get)
    monkeypatch.setattr(gs_store_module.Cache.workout, 'cache_gif_filename', fake_cache)

    url = asyncio.run(storage.find_gif('Push Up', {'pushup': ['Push Up']}))
    assert url == 'https://storage.googleapis.com/bucket/pushup.gif'
    assert stored['push up'] == 'pushup.gif'


