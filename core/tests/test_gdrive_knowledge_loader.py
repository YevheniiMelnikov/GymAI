from __future__ import annotations

from typing import Any

import pytest


class _FakeService:
    def list(self, q: str, fields: str) -> "_FakeService":
        return self

    def execute(self) -> dict[str, list[dict[str, Any]]]:
        return {"files": [{"id": "1", "name": "doc.txt", "size": "4"}]}


@pytest.mark.asyncio
async def test_load_calls_add_text_without_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.app_settings as app_settings

    monkeypatch.setattr(app_settings.settings, "KNOWLEDGE_BASE_FOLDER_ID", "folder", raising=False)
    monkeypatch.setattr(app_settings.settings, "MAX_FILE_SIZE_MB", 10, raising=False)
    from ai_coach.agent.knowledge.gdrive_knowledge_loader import GDriveDocumentLoader

    calls: list[tuple[str, str, list[str] | None]] = []

    async def add_text(text: str, *, dataset: str, node_set: list[str] | None = None) -> None:
        calls.append((text, dataset, node_set))

    loader = GDriveDocumentLoader(add_text)

    async def download_file(file_id: str) -> bytes:
        assert file_id == "1"
        return b"hello"

    monkeypatch.setattr(loader, "_get_drive_files_service", lambda: _FakeService())
    monkeypatch.setattr(loader, "_download_file", download_file)

    await loader.load()

    assert calls == [("hello", loader._dataset_name, ["gdrive:doc.txt"])], calls


@pytest.mark.asyncio
async def test_load_logs_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.app_settings as app_settings

    monkeypatch.setattr(app_settings.settings, "KNOWLEDGE_BASE_FOLDER_ID", "folder", raising=False)
    monkeypatch.setattr(app_settings.settings, "MAX_FILE_SIZE_MB", 10, raising=False)
    from ai_coach.agent.knowledge.gdrive_knowledge_loader import GDriveDocumentLoader
    from loguru import logger

    messages: list[str] = []

    def fake_exception(msg: str, *a: object, **k: object) -> None:
        messages.append(msg)

    monkeypatch.setattr(logger, "exception", fake_exception)

    async def add_text(text: str, *, dataset: str, node_set: list[str] | None = None) -> None:
        raise RuntimeError("boom")

    loader = GDriveDocumentLoader(add_text)

    async def download_file(file_id: str) -> bytes:
        assert file_id == "1"
        return b"hello"

    monkeypatch.setattr(loader, "_get_drive_files_service", lambda: _FakeService())
    monkeypatch.setattr(loader, "_download_file", download_file)

    await loader.load()

    assert messages == ["Failed to process doc.txt (id=1)"]
