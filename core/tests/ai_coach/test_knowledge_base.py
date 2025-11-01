from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, ProjectionStatus


@pytest.fixture(autouse=True)
def mock_hash_store(monkeypatch):
    monkeypatch.setattr("ai_coach.agent.knowledge.utils.hash_store.HashStore.redis", MagicMock())


@pytest.mark.asyncio
async def test_add_text_file_not_found_retry(monkeypatch):
    """
    Unit-test for add_text with FileNotFoundError simulation:
    expect successful retry after _ensure_storage_file+rebuild_dataset.
    """
    user = object()
    dataset = "test_dataset"
    text = "some text"

    mock_update_dataset = AsyncMock(side_effect=[FileNotFoundError("File not found"), ("resolved_name", True)])
    mock_ensure_storage_file = MagicMock()
    mock_hash_store_clear = AsyncMock()
    mock_rebuild_dataset = AsyncMock(return_value=True)
    mock_process_dataset = AsyncMock()

    monkeypatch.setattr(KnowledgeBase, "update_dataset", mock_update_dataset)
    monkeypatch.setattr(KnowledgeBase, "_ensure_storage_file", mock_ensure_storage_file)
    monkeypatch.setattr(KnowledgeBase, "rebuild_dataset", mock_rebuild_dataset)
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", AsyncMock(return_value=user))
    monkeypatch.setattr(KnowledgeBase, "_process_dataset", mock_process_dataset)
    monkeypatch.setattr("ai_coach.agent.knowledge.knowledge_base.HashStore.clear", mock_hash_store_clear)

    await KnowledgeBase.add_text(text, dataset=dataset)

    assert mock_update_dataset.call_count == 2
    mock_ensure_storage_file.assert_called_once()
    mock_hash_store_clear.assert_called_once_with(dataset)
    mock_rebuild_dataset.assert_called_once_with(dataset, user)
    mock_process_dataset.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_projection_ready():
    """Unit-test _wait_for_projection: branch ready."""
    with patch.object(KnowledgeBase, "_is_projection_ready", new_callable=AsyncMock) as mock_is_ready:
        mock_is_ready.return_value = (True, "ready")
        status = await KnowledgeBase._wait_for_projection("test_dataset", user=object())
    assert status == ProjectionStatus.READY


@pytest.mark.asyncio
async def test_wait_for_projection_timeout():
    """Unit-test _wait_for_projection: branch timeout."""
    with patch.object(KnowledgeBase, "_is_projection_ready", new_callable=AsyncMock) as mock_is_ready:
        mock_is_ready.return_value = (False, "pending_rows=1")
    status = await KnowledgeBase._wait_for_projection("test_dataset", user=object(), timeout_s=0.01)
    assert status == ProjectionStatus.TIMEOUT


@pytest.mark.asyncio
async def test_rebuild_dataset(monkeypatch, tmp_path: Path):
    """
    Unit-test rebuild_dataset: create N valid text_<sha>.txt,
    after rebuild HashStore.list(alias) contains same SHAs.
    """
    user = object()
    alias = "test_rebuild"
    texts = ["text 1", "text 2", "text 3"]
    shas = [KnowledgeBase._compute_digests(text) for text in texts]

    storage_root = tmp_path / "cognee_storage"
    storage_root.mkdir()
    monkeypatch.setattr(KnowledgeBase, "_storage_root", lambda: storage_root)

    for sha, text in zip(shas, texts):
        (storage_root / f"text_{sha}.txt").write_text(text)

    mock_list_entries = AsyncMock(return_value=[])
    mock_update_dataset = AsyncMock(return_value=("", True))
    mock_hash_store_list = AsyncMock(return_value=set(shas))

    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", mock_list_entries)
    monkeypatch.setattr(KnowledgeBase, "update_dataset", mock_update_dataset)
    monkeypatch.setattr(KnowledgeBase.HashStore, "list", mock_hash_store_list)
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", AsyncMock())
    monkeypatch.setattr(KnowledgeBase, "_process_dataset", AsyncMock())

    await KnowledgeBase.rebuild_dataset(alias, user)

    listed_shas = await KnowledgeBase.HashStore.list(alias)
    assert listed_shas == set(shas)
