from typing import Any, Protocol, Sequence

import cognee
from loguru import logger

from ai_coach.agent.knowledge.utils.cognee_compat import resolve_get_cache_engine
from ai_coach.agent.knowledge.utils.memify_scheduler import try_lock_chat_summary
from ai_coach.types import MessageRole
from config.app_settings import settings
from core.utils.redis_lock import get_redis_client_for_db, redis_try_lock


class SummarizeMessages(Protocol):
    async def __call__(
        self,
        messages: Sequence[str],
        *,
        language: str,
        profile_id: int,
    ) -> str: ...


class UpdateDataset(Protocol):
    async def __call__(
        self,
        text: str,
        dataset: str,
        user: Any | None = None,
        node_set: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        force_ingest: bool = False,
        trigger_projection: bool = True,
    ) -> tuple[str, bool]: ...


class InvokeMemify(Protocol):
    async def __call__(
        self,
        memify_fn: Any,
        *,
        datasets: list[str],
        user: Any | None,
    ) -> None: ...


class SessionCacheService:
    """Manage cached chat sessions and summarization flow for the coach."""

    def __init__(self, dataset_service: Any) -> None:
        self._dataset_service = dataset_service

    @staticmethod
    def _session_key(user_id: str, session_id: str) -> str:
        return f"agent_sessions:{user_id}:{session_id}"

    async def load_session_entries(self, profile_id: int, *, limit_pairs: int | None = None) -> list[dict[str, Any]]:
        getter, _module = resolve_get_cache_engine()
        if getter is None:
            logger.debug(
                "cognee_cache_engine_unavailable profile_id={} detail=get_cache_engine_missing",
                profile_id,
            )
            return []

        user = await self._dataset_service.get_cognee_user()
        user_id = self._dataset_service.to_user_id(user)
        if not user_id:
            return []
        session_id = self._dataset_service.session_id_for_profile(profile_id)
        cache = getter(lock_key=f"chat_session:{profile_id}")
        if cache is None:
            return []
        try:
            if limit_pairs is not None:
                entries = await cache.get_latest_qa(user_id, session_id, last_n=limit_pairs)
                return list(entries or [])
            entries = await cache.get_all_qas(user_id, session_id)
            return list(entries or [])
        except Exception as exc:  # noqa: BLE001
            logger.debug("chat_session_fetch_failed profile_id={} detail={}", profile_id, exc)
            return []

    @staticmethod
    def entries_to_messages(entries: Sequence[dict[str, Any]]) -> list[str]:
        messages: list[str] = []
        for entry in entries:
            question = str(entry.get("question") or "").strip()
            answer = str(entry.get("answer") or "").strip()
            if question:
                messages.append(f"{MessageRole.CLIENT.value}: {question}")
            if answer:
                messages.append(f"{MessageRole.AI_COACH.value}: {answer}")
        return messages

    async def maybe_summarize_session(
        self,
        profile_id: int,
        *,
        summarize_messages: SummarizeMessages,
        update_dataset: UpdateDataset,
        invoke_memify: InvokeMemify,
        language: str | None = None,
    ) -> dict[str, Any]:
        pair_limit = int(settings.AI_COACH_CHAT_SUMMARY_PAIR_LIMIT)
        if pair_limit <= 0:
            return {"status": "skipped", "reason": "disabled"}
        dedupe_ttl = max(pair_limit * 5, 60)
        if not await try_lock_chat_summary(profile_id, dedupe_ttl):
            return {"status": "skipped", "reason": "dedupe_lock"}
        lock_key = f"locks:chat_summary:{profile_id}"
        async with redis_try_lock(lock_key, ttl_ms=180_000, wait=False) as got_lock:
            if not got_lock:
                return {"status": "skipped", "reason": "lock_held"}
            entries = await self.load_session_entries(profile_id)
            processed_len = len(entries)
            if processed_len < pair_limit:
                return {"status": "skipped", "reason": "below_threshold", "messages": processed_len}
            messages = self.entries_to_messages(entries)
            if not messages:
                return {"status": "skipped", "reason": "empty"}
            summary_language = language or settings.DEFAULT_LANG
            summary = await summarize_messages(messages, language=summary_language, profile_id=profile_id)
            if not summary:
                return {"status": "skipped", "reason": "summary_empty", "messages": processed_len}
            user = await self._dataset_service.get_cognee_user()
            if user is None:
                return {"status": "skipped", "reason": "user_context_unavailable"}
            summary_text = summary.strip()
            if not summary_text:
                return {"status": "skipped", "reason": "summary_empty", "messages": processed_len}
            summary_payload = f"{MessageRole.AI_COACH.value}: {summary_text}"
            node_set = [f"profile:{profile_id}", "chat_summary"]
            metadata = {"channel": "chat", "kind": "summary", "language": summary_language}
            dataset = self._dataset_service.chat_dataset_name(profile_id)
            resolved_name, created = await update_dataset(
                summary_payload,
                dataset,
                user,
                node_set=node_set,
                metadata=metadata,
                force_ingest=False,
                trigger_projection=True,
            )
            if created:
                alias = self._dataset_service.alias_for_dataset(resolved_name)
                memify_fn = getattr(cognee, "memify", None)
                user_ctx = self._dataset_service.to_user_ctx(user)
                if callable(memify_fn) and user_ctx is not None:
                    await invoke_memify(memify_fn, datasets=[alias], user=user_ctx)
            user_id = self._dataset_service.to_user_id(user)
            session_id = self._dataset_service.session_id_for_profile(profile_id)
            if user_id:
                try:
                    client = get_redis_client_for_db(settings.AI_COACH_REDIS_CHAT_DB)
                    await client.delete(self._session_key(user_id, session_id))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("chat_session_clear_failed profile_id={} detail={}", profile_id, exc)
            return {
                "status": "ok",
                "reason": "session_cache",
                "messages": processed_len,
                "summary_len": len(summary_text),
            }

    async def get_message_history(self, profile_id: int, limit: int | None = None) -> list[str]:
        limit_value = limit or settings.CHAT_HISTORY_LIMIT
        pair_limit = int(settings.AI_COACH_CHAT_SUMMARY_PAIR_LIMIT)
        default_pairs = pair_limit if pair_limit > 0 else 0
        pairs_from_limit = max(int(limit_value / 2), 1) if limit_value else 0
        if default_pairs and pairs_from_limit:
            pairs_to_fetch = min(default_pairs, pairs_from_limit)
        else:
            pairs_to_fetch = default_pairs or pairs_from_limit or None
        entries = await self.load_session_entries(profile_id, limit_pairs=pairs_to_fetch)
        messages = self.entries_to_messages(entries)
        return messages[-limit_value:] if limit_value else messages
