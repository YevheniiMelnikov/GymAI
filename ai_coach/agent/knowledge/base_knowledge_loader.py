from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class KnowledgeLoader(Protocol):
    """Common interface for external knowledge loaders."""

    async def load(self) -> None:
        """Perform a full sync from the source into Cognee."""

    async def refresh(self) -> None: ...

    async def supports(self, filename: str, mime_type: str | None = None) -> bool: ...

    async def list_items(self) -> Iterable[str]: ...

    async def download(self, item_id: str) -> bytes: ...

    async def shutdown(self) -> None: ...
