import importlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import ai_coach.agent.knowledge.gdrive_knowledge_loader as loader_module


@dataclass(frozen=True)
class _FakeRequest:
    payload: dict[str, Any]

    def execute(self) -> dict[str, Any]:
        return self.payload


class _FakeDriveFilesService:
    def __init__(self, folder_to_items: dict[str, list[dict[str, Any]]]) -> None:
        self._folder_to_items = folder_to_items

    def list(  # noqa: A003 - keep parity with googleapiclient
        self,
        *,
        q: str,
        fields: str | None = None,
        pageToken: str | None = None,  # noqa: N803 - keep parity with googleapiclient
        pageSize: int | None = None,  # noqa: N803 - keep parity with googleapiclient
    ) -> _FakeRequest:
        del fields, pageToken, pageSize
        # q looks like "'<folder_id>' in parents and trashed = false"
        folder_id = q.split("'", 2)[1]
        return _FakeRequest({"files": list(self._folder_to_items.get(folder_id, [])), "nextPageToken": None})


def test_gdrive_loader_scans_subfolders_and_preserves_paths(monkeypatch) -> None:
    importlib.reload(loader_module)  # conftest swaps the class; reload restores the real implementation
    GDriveDocumentLoader = loader_module.GDriveDocumentLoader
    kb = SimpleNamespace(GLOBAL_DATASET="kb_global")
    loader = GDriveDocumentLoader(kb)

    folder_mime = "application/vnd.google-apps.folder"
    tree = {
        "root": [
            {"id": "folder-1", "name": "programs", "mimeType": folder_mime, "modifiedTime": "t1"},
            {"id": "file-1", "name": "intro.md", "mimeType": "text/markdown", "size": "12", "modifiedTime": "t2"},
        ],
        "folder-1": [
            {"id": "folder-2", "name": "elderly", "mimeType": folder_mime, "modifiedTime": "t3"},
            {"id": "file-2", "name": "basics.txt", "mimeType": "text/plain", "size": "10", "modifiedTime": "t4"},
        ],
        "folder-2": [
            {"id": "file-3", "name": "contraindications.pdf", "mimeType": "application/pdf", "size": "9"},
        ],
    }
    monkeypatch.setattr(loader, "_get_drive_files_service", lambda: _FakeDriveFilesService(tree))

    items = loader._scan_drive_tree("root")
    paths = sorted(item.get("kb_path") for item in items)
    assert paths == ["intro.md", "programs/basics.txt", "programs/elderly/contraindications.pdf"]
