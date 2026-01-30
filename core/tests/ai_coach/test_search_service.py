import asyncio

import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.knowledge.utils.search import SearchService
from ai_coach.exceptions import KnowledgeBaseUnavailableError


class _DatasetServiceStub:
    _PROJECTED_DATASETS: set[str] = set()

    def alias_for_dataset(self, dataset: str) -> str:
        return dataset

    async def get_counts(self, alias: str, user: object) -> dict[str, int]:
        return {"text_rows": 1, "chunk_rows": 0, "graph_nodes": 0, "graph_edges": 0}

    async def get_row_count(self, alias: str, user: object) -> int:
        return 0

    async def ensure_dataset_exists(self, alias: str, user_ctx: object) -> None:
        return None

    def log_once(self, *args: object, **kwargs: object) -> None:
        return None

    def to_user_ctx(self, user: object) -> object:
        return user


class _ProjectionServiceStub:
    async def ensure_dataset_projected(self, alias: str, user: object, timeout_s: float = 2.0) -> ProjectionStatus:
        return ProjectionStatus.TIMEOUT


def test_search_service_has_rows_but_unavailable() -> None:
    async def runner() -> None:
        service = SearchService(_DatasetServiceStub(), _ProjectionServiceStub())
        with pytest.raises(KnowledgeBaseUnavailableError) as exc_info:
            await service._search_single_query(  # pyrefly: ignore[private-use]
                "query",
                ["dataset"],
                user={"id": 1},
                k=3,
                profile_id=1,
                request_id="rid-1",
                session_id="",
            )
        assert exc_info.value.reason == "knowledge_base_unavailable"

    asyncio.run(runner())
