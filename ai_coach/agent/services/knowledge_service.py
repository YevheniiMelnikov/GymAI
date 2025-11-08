from loguru import logger

from ai_coach.agent.knowledge.helpers import (
    build_knowledge_entries,
    filter_entries_for_prompt,
)
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, KnowledgeSnippet


class KnowledgeService:
    @staticmethod
    async def collect_entries(
        kb: KnowledgeBase,
        client_id: int,
        query: str,
        *,
        request_id: str | None,
        limit: int = 6,
    ) -> tuple[list[str], list[str], list[str], list[KnowledgeSnippet]]:
        actor = await kb.dataset_service.get_cognee_user()
        candidate_datasets = [
            kb.dataset_service.dataset_name(client_id),
            kb.dataset_service.chat_dataset_name(client_id),
            kb.GLOBAL_DATASET,
        ]
        unique_datasets: list[str] = []
        seen: set[str] = set()
        for dataset in candidate_datasets:
            alias = kb.dataset_service.alias_for_dataset(dataset)
            if alias in seen:
                continue
            seen.add(alias)
            unique_datasets.append(alias)
        for dataset in unique_datasets:
            try:
                await kb.projection_service.ensure_dataset_projected(dataset, actor, timeout_s=2.0)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"knowledge_projection_skip dataset={dataset} detail={exc}")

        snippets = await kb.search(query, client_id, limit, request_id=request_id)
        entry_ids, entries, datasets = build_knowledge_entries(snippets)
        entry_ids, entries, datasets = filter_entries_for_prompt(query, entry_ids, entries, datasets)
        dataset_aliases = [kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in datasets]
        if entry_ids:
            return entry_ids, entries, dataset_aliases, list(snippets)
        try:
            fallback_raw = await kb.fallback_entries(client_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"agent.ask fallback_entries_failed client_id={client_id} detail={exc}")
            fallback_raw = []
        fallback_snippets = [
            KnowledgeSnippet(text=text, dataset=dataset, kind="document") for text, dataset in fallback_raw
        ]
        fallback_ids, fallback_entries, fallback_datasets = build_knowledge_entries(fallback_snippets)
        fallback_ids, fallback_entries, fallback_datasets = filter_entries_for_prompt(
            query, fallback_ids, fallback_entries, fallback_datasets
        )
        alias_fallbacks = [
            kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in fallback_datasets
        ]
        return fallback_ids, fallback_entries, alias_fallbacks, list(snippets)
