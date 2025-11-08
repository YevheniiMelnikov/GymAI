import json
import os
from functools import wraps
from time import perf_counter
from typing import Any, Awaitable, Callable, ClassVar, Mapping, Optional, Sequence, TypeVar, cast

from loguru import logger  # pyrefly: ignore[import-error]
from openai import AsyncOpenAI  # pyrefly: ignore[import-error]
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart  # pyrefly: ignore[import-error]
from pydantic_ai.models.openai import OpenAIChatModel  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings  # pyrefly: ignore[import-error]

from config.app_settings import settings
from ai_coach.agent.base import AgentDeps
from ai_coach.agent.prompts import COACH_SYSTEM_PROMPT, ASK_AI_USER_PROMPT, agent_instructions
from ai_coach.agent.tools import toolset
from ai_coach.agent.utils import get_knowledge_base, resolve_language_name
from ai_coach.agent.knowledge.knowledge_base import KnowledgeSnippet
from ai_coach.agent.knowledge.helpers import (
    build_knowledge_entries,
    filter_entries_for_prompt,
    format_knowledge_entries,
    truncate_text,
    unique_sources,
)
from ai_coach.agent.services.knowledge_service import KnowledgeService
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.types import MessageRole
from core.schemas import QAResponse


TOutput = TypeVar("TOutput", bound=BaseModel)


class LLMHelper:
    _agent: Optional[Agent] = None
    _completion_client: ClassVar[AsyncOpenAI | None] = None
    _completion_model_name: ClassVar[str | None] = None

    _LANGUAGE_CODE_ALIASES: ClassVar[dict[str, str]] = {
        "ua": "uk",
        "ua-ua": "uk",
        "uk-ua": "uk",
        "ukrainian": "uk",
        "eng": "en",
        "en-us": "en",
        "english": "en",
        "ru-ru": "ru",
        "rus": "ru",
        "russian": "ru",
    }

    @classmethod
    def _language_context(cls, deps: AgentDeps) -> tuple[str, str]:
        default_lang: str = getattr(settings, "DEFAULT_LANG", "en") or "en"
        raw_locale = (deps.locale or default_lang).strip()
        if not raw_locale:
            raw_locale = default_lang
        normalized = raw_locale.replace("_", "-").lower()
        code = cls._LANGUAGE_CODE_ALIASES.get(normalized)
        if code is None and "-" in normalized:
            primary = normalized.split("-", 1)[0]
            code = cls._LANGUAGE_CODE_ALIASES.get(primary, primary)
        if code is None:
            code = cls._LANGUAGE_CODE_ALIASES.get(normalized, normalized)
        if not code:
            code = default_lang.lower()
        if len(code) != 2 or not code.isalpha():
            fallback = cls._LANGUAGE_CODE_ALIASES.get(default_lang.lower(), default_lang.lower())
            code = fallback if len(fallback) == 2 and fallback.isalpha() else "en"
        code = code.lower()
        descriptor = resolve_language_name(code)
        display = f"{descriptor} ({code})" if descriptor != code else code
        return code, display

    @classmethod
    def _lang(cls, deps: AgentDeps) -> str:
        code, _ = cls._language_context(deps)
        return code

    @classmethod
    def _init_agent(cls) -> Any:
        if Agent is None or OpenAIChatModel is None:
            raise RuntimeError("pydantic_ai package is required")

        provider_config: Any = settings.AGENT_PROVIDER
        if isinstance(provider_config, str):
            provider_name: str | None = provider_config.strip().lower()
        else:
            provider_name = None

        provider: Any = provider_config
        client_override: AsyncOpenAI | None = None

        if provider_name == "openrouter":
            try:
                from pydantic_ai.providers.openrouter import OpenRouterProvider  # pyrefly: ignore[import-error]
            except Exception as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("OpenRouter provider is not available") from exc

            api_key: str = settings.LLM_API_KEY
            if not api_key:
                raise RuntimeError("LLM_API_KEY must be configured when using the OpenRouter provider")
            provider = OpenRouterProvider(api_key=api_key)
        else:
            if settings.LLM_API_KEY or settings.LLM_API_URL:
                client_override = AsyncOpenAI(
                    api_key=settings.LLM_API_KEY or None,
                    base_url=settings.LLM_API_URL or None,
                )

        model = OpenAIChatModel(
            model_name=settings.AGENT_MODEL,
            provider=provider,
            settings=ModelSettings(
                timeout=float(settings.COACH_AGENT_TIMEOUT),
            ),
        )

        if client_override is not None:
            model.client = client_override

        cls._agent = Agent(
            model=model,
            deps_type=AgentDeps,
            toolsets=[toolset],
            retries=settings.COACH_AGENT_RETRIES,
            system_prompt=COACH_SYSTEM_PROMPT,
        )  # pyrefly: ignore[no-matching-overload]
        cls._ensure_llm_logging(cls._agent)

        @cls._agent.system_prompt  # pyrefly: ignore[no-matching-overload]
        async def coach_sys(ctx: RunContext[AgentDeps]) -> str:  # pyrefly: ignore[unsupported-operation]
            lang = ctx.deps.locale or settings.DEFAULT_LANG
            client_name = ctx.deps.client_name or "the client"
            return f"Client's name: {client_name}\nClient's language: {lang}"

        @cls._agent.instructions  # pyrefly: ignore[no-matching-overload]
        def agent_instr(ctx: RunContext[AgentDeps]) -> str:  # pragma: no cover - runtime config
            mode = ctx.deps.mode.value if ctx.deps.mode else "ask_ai"
            return agent_instructions(mode)

        return cls._agent

    @classmethod
    def _get_agent(cls) -> Any:
        if cls._agent is None:
            return cls._init_agent()
        return cls._agent

    @staticmethod
    def _normalize_output(
        raw: Any,
        expected: type[TOutput],
    ) -> TOutput:
        value = getattr(raw, "output", raw)
        if isinstance(value, expected):
            return value
        if not issubclass(expected, BaseModel):
            raise TypeError(f"Unsupported output type: {expected!r}")
        return expected.model_validate(value)

    @staticmethod
    async def _message_history(client_id: int) -> list[ModelMessage]:
        kb = get_knowledge_base()
        raw = await kb.get_message_history(client_id)
        history: list[ModelMessage] = []
        for item in raw:
            if item.startswith(f"{MessageRole.CLIENT.value}:"):
                text = item.split(":", 1)[1]
                history.append(ModelRequest.user_text_prompt(text.strip()))
            elif item.startswith(f"{MessageRole.AI_COACH.value}:"):
                text = item.split(":", 1)[1]
                history.append(ModelResponse(parts=[TextPart(content=text.strip())]))
        return history

    @classmethod
    async def _fallback_answer_question(
        cls,
        prompt: str,
        deps: AgentDeps,
        history: list[ModelMessage],
        *,
        prefetched_knowledge: Sequence[KnowledgeSnippet] | None = None,
    ) -> QAResponse | None:
        if deps.fallback_used:
            logger.debug(f"agent.ask fallback skipped client_id={deps.client_id} reason=already_used")
            return None
        deps.fallback_used = True
        logger.warning(
            f"agent.ask fallback_invoked client_id={deps.client_id} reason=model_empty_response history={len(history)}"
        )
        client, model_name = cls._get_completion_client()
        cls._ensure_llm_logging(client, model_name)
        knowledge: Sequence[KnowledgeSnippet]
        kb = get_knowledge_base()
        if prefetched_knowledge is not None:
            knowledge = prefetched_knowledge
        else:
            try:
                knowledge = await kb.search(
                    prompt,
                    deps.client_id,
                    6,
                    request_id=deps.request_rid,
                )
            except Exception as exc:  # noqa: BLE001 - log and continue with empty knowledge
                logger.warning(f"agent.ask fallback knowledge_failed client_id={deps.client_id} error={exc}")
                knowledge = []
        entry_ids, entries, entry_datasets = build_knowledge_entries(knowledge)
        entry_ids, entries, entry_datasets = filter_entries_for_prompt(prompt, entry_ids, entries, entry_datasets)
        entry_datasets = [
            kb.dataset_service.alias_for_dataset(dataset) if dataset else "" for dataset in entry_datasets
        ]
        deps.knowledge_base_empty = len(entry_ids) == 0
        deps.kb_used = not deps.knowledge_base_empty
        _, language_label = cls._language_context(deps)
        knowledge_section = format_knowledge_entries(entry_ids, entries)
        system_prompt = COACH_SYSTEM_PROMPT
        user_prompt = ASK_AI_USER_PROMPT.format(
            language=language_label,
            question=prompt,
        )
        if knowledge_section:
            user_prompt = f"{user_prompt}\n\nKnowledge entries:\n{knowledge_section}"
        response = await cls._complete_with_retries(
            client,
            system_prompt,
            user_prompt,
            entry_ids,
            client_id=deps.client_id,
            max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
            model=model_name,
        )
        if response is not None:
            result = cls._finalize_response(
                response,
                entry_ids,
                entry_datasets,
                deps=deps,
            )
            result.sources = unique_sources(entry_datasets)
            logger.info(
                (
                    f"agent.ask fallback_success client_id={deps.client_id} answer_len={len(result.answer)} "
                    f"sources={','.join(result.sources)} kb_empty={deps.knowledge_base_empty}"
                )
            )
            return result
        if entry_ids:
            logger.warning(
                "agent.ask fallback missing_completion client_id={} kb_entries={} reason=empty_llm".format(
                    deps.client_id,
                    len(entry_ids),
                )
            )
            return None
        deps.knowledge_base_empty = True
        logger.warning(f"agent.ask fallback missing_answer client_id={deps.client_id} kb_empty=True")
        return None

    @classmethod
    async def _complete_with_retries(
        cls,
        client: AsyncOpenAI,
        system_prompt: str,
        user_prompt: str,
        entry_ids: Sequence[str],
        *,
        client_id: int,
        max_tokens: int,
        model: str | None = None,
        continuation_attempt: int = 0,
        continuation_context: str | None = None,
    ) -> QAResponse | None:
        max_attempts = 2 if settings.AI_COACH_EMPTY_COMPLETION_RETRY else 1
        model_id = model or settings.AGENT_MODEL
        full_content = ""
        final_finish_reason = "unknown"

        for attempt in range(max_attempts):
            if attempt > 0:
                logger.info(
                    ("llm.retry client_id={} model={} max_tokens={} attempt={} json_modes=0").format(
                        client_id, model_id, attempt, 0
                    )
                )
            current_user_prompt = user_prompt
            if continuation_attempt > 0:
                previous = continuation_context if continuation_context is not None else full_content
                if previous:
                    snippet = truncate_text(previous, 1200)
                    current_user_prompt = (
                        f"{user_prompt}\n\n"
                        "Continue the previous answer from where it stopped. "
                        "Do not repeat the text below; only add the missing continuation.\n"
                        f"Already sent to the client:\n{snippet}"
                    )

            try:
                response = await cls._run_completion(
                    client,
                    system_prompt,
                    current_user_prompt,
                    model=model_id,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    ("agent.ask completion_failed client_id={} model={} attempt={} error={}").format(
                        client_id, model_id, attempt, exc
                    )
                )
                continue
            meta = cls._llm_response_metadata(response)
            content = cls._extract_choice_content(response, client_id=client_id)
            full_content += content
            final_finish_reason = meta.get("finish_reason") or "unknown"

            if final_finish_reason == "length" and continuation_attempt == 0:
                logger.info(
                    ("llm.continuation_needed client_id={} model={} max_tokens={} current_len={}").format(
                        client_id, model_id, max_tokens, len(full_content)
                    )
                )
                continuation_response = await cls._complete_with_retries(
                    client,
                    system_prompt,
                    user_prompt,
                    entry_ids,
                    client_id=client_id,
                    max_tokens=getattr(settings, "AI_COACH_CONTINUATION_MAX_TOKENS", 600),
                    model=model,
                    continuation_attempt=1,
                    continuation_context=full_content,
                )
                if continuation_response and continuation_response.answer:
                    full_content += continuation_response.answer
                    final_finish_reason = (
                        cls._llm_response_metadata(continuation_response).get("finish_reason") or "stop"
                    )
                break
            else:
                break

        if full_content:
            raw_text = full_content.strip()
            answer, sources = cls._parse_fallback_content(
                full_content,
                entry_ids,
                client_id=client_id,
            )
            if not answer.strip() and raw_text:
                logger.debug(
                    "llm.partial_content_used client_id={} reason={} model={} preserved_len={}".format(
                        client_id,
                        final_finish_reason,
                        model_id,
                        len(raw_text),
                    )
                )
                answer = raw_text
                sources = list(entry_ids) or ["general_knowledge"]
            if answer.strip():
                normalized_sources = list(sources) if sources else list(entry_ids) or ["general_knowledge"]
                return QAResponse(answer=answer, sources=normalized_sources)
        log_message = ("llm.response.empty client_id={} reason={} model={} final_content_len={}").format(
            client_id,
            final_finish_reason,
            model_id,
            len(full_content),
        )
        log_fn = logger.info if final_finish_reason == "length" else logger.warning
        log_fn(log_message)
        return None

    @classmethod
    def _collect_text_fragments(cls, value: Any) -> list[str]:
        fragments: list[str] = []
        cls._append_text_fragment(value, fragments)
        return fragments

    @classmethod
    def _append_text_fragment(cls, value: Any, fragments: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, (bytes, bytearray)):
            text = value.decode("utf-8", "ignore").strip()
            if text:
                fragments.append(text)
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                fragments.append(text)
            return
        if hasattr(value, "text") and not isinstance(value, (str, bytes)):
            cls._append_text_fragment(getattr(value, "text"), fragments)
            return
        if hasattr(value, "content") and not isinstance(value, (str, bytes)):
            cls._append_text_fragment(getattr(value, "content"), fragments)
            return
        if isinstance(value, Mapping):
            for key in ("text", "content", "value", "message"):
                if key in value:
                    cls._append_text_fragment(value[key], fragments)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                cls._append_text_fragment(item, fragments)
            return

    @staticmethod
    def _extract_message_content(content: Any) -> str:
        fragments = LLMHelper._collect_text_fragments(content)
        if fragments:
            return "\n".join(fragments)
        if hasattr(content, "model_dump"):
            try:
                dumped = content.model_dump()
            except Exception:  # noqa: BLE001
                dumped = None
            if dumped:
                fragments = LLMHelper._collect_text_fragments(dumped)
                if fragments:
                    return "\n".join(fragments)
        return ""

    @staticmethod
    def _model_identifier(model: Any) -> str:
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if not model_name:
            return settings.AGENT_MODEL
        return str(model_name)

    @classmethod
    def _get_completion_client(cls) -> tuple[AsyncOpenAI, str]:
        if cls._completion_client is not None and cls._completion_model_name is not None:
            return cls._completion_client, cls._completion_model_name

        agent = cls._get_agent()
        model = getattr(agent, "model", None)
        client = getattr(model, "client", None)
        if isinstance(client, AsyncOpenAI):
            cls._completion_client = client
            cls._completion_model_name = cls._model_identifier(model)
            return client, cls._completion_model_name

        cls._completion_client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY or None,
            base_url=settings.LLM_API_URL or None,
        )
        cls._completion_model_name = settings.AGENT_MODEL
        return cls._completion_client, cls._completion_model_name

    @classmethod
    def _ensure_llm_logging(cls, target: Any, model_id: str | None = None) -> None:
        client: AsyncOpenAI | None
        if isinstance(target, AsyncOpenAI):
            client = target
        else:
            client = getattr(target, "client", None)
        if not isinstance(client, AsyncOpenAI):
            return
        if getattr(client, "_gymbot_wrapped", False):
            return
        chat = getattr(client, "chat", None)
        completions = getattr(chat, "completions", None)
        if completions is None:
            return
        original_create = getattr(completions, "create", None)
        if not callable(original_create):
            return
        typed_create = cast(Callable[..., Awaitable[Any]], original_create)

        resolved_model = model_id or settings.AGENT_MODEL

        @wraps(typed_create)
        async def wrapped_create(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - external signature
            start = perf_counter()
            request_meta = cls._llm_request_metadata(kwargs)
            logger.debug(
                (
                    "llm.request model={} json_format={} stream={} messages={} system_len={} user_len={} "
                    "temperature={} max_tokens={} tool_choice={}"
                ).format(
                    resolved_model,
                    request_meta["json_format"],
                    request_meta["stream"],
                    request_meta["messages"],
                    request_meta["system_len"],
                    request_meta["user_len"],
                    request_meta["temperature"],
                    request_meta["max_tokens"],
                    request_meta["tool_choice"],
                )
            )
            try:
                response = await typed_create(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                latency = (perf_counter() - start) * 1000.0
                logger.warning(f"llm.response.error model={resolved_model} latency_ms={latency:.0f} error={exc}")
                raise
            latency = (perf_counter() - start) * 1000.0
            response_meta = cls._llm_response_metadata(response)
            logger.debug(
                (
                    "llm.response model={} choices={} finish_reason={} content_len={} "
                    "has_tool_calls={} prompt_tokens={} completion_tokens={} total_tokens={} "
                    "latency_ms={:.0f} preview={}"
                ).format(
                    resolved_model,
                    response_meta["choices"],
                    response_meta["finish_reason"],
                    response_meta["content_len"],
                    response_meta["has_tool_calls"],
                    response_meta["prompt_tokens"],
                    response_meta["completion_tokens"],
                    response_meta["total_tokens"],
                    latency,
                    response_meta["preview"],
                )
            )
            if os.getenv("LOG_LLM_RAW", "").lower() in {"1", "true", "yes"}:
                raw_snapshot, raw_keys = cls._raw_choice_snapshot(response)
                logger.debug(
                    "llm.response.raw model={} raw_first_200={} raw_keys={}".format(
                        resolved_model,
                        raw_snapshot,
                        raw_keys or "na",
                    )
                )
            return response

        completions.create = wrapped_create  # type: ignore[assignment]
        setattr(client, "_gymbot_wrapped", True)

    @staticmethod
    def _llm_request_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
        messages = kwargs.get("messages") or []
        system_len = 0
        user_len = 0
        total_messages = 0
        for message in messages:
            role = str(message.get("role", "")).lower()
            content = message.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            else:
                text = str(content)
            total_messages += 1
            length = len(text.strip())
            if role == "system":
                system_len += length
            elif role == "user":
                user_len += length
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        tool_choice = kwargs.get("tool_choice")
        return {
            "json_format": "response_format" in kwargs,
            "stream": bool(kwargs.get("stream", False)),
            "messages": total_messages,
            "system_len": system_len,
            "user_len": user_len,
            "temperature": temperature if temperature is not None else "na",
            "max_tokens": max_tokens if max_tokens is not None else "na",
            "tool_choice": tool_choice if tool_choice is not None else "na",
        }

    @classmethod
    def _llm_response_metadata(cls, response: Any) -> dict[str, Any]:
        choices = getattr(response, "choices", None) or []
        first_choice = choices[0] if choices else None
        message = getattr(first_choice, "message", None)
        if message is None and isinstance(first_choice, Mapping):
            message = first_choice.get("message")
        if isinstance(message, Mapping):
            tool_calls = message.get("tool_calls")
        else:
            tool_calls = getattr(message, "tool_calls", None)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if isinstance(first_choice, Mapping):
            finish_reason = str(first_choice.get("finish_reason", "") or "")
        else:
            finish_reason = getattr(first_choice, "finish_reason", "") if first_choice else ""
        preview = cls._message_preview(message) if message is not None else ""
        extracted_text = cls._extract_choice_content(response, client_id=None)
        return {
            "choices": len(choices),
            "finish_reason": finish_reason or "",
            "content_len": len(extracted_text),
            "has_tool_calls": bool(tool_calls),
            "prompt_tokens": prompt_tokens if prompt_tokens is not None else "na",
            "completion_tokens": completion_tokens if completion_tokens is not None else "na",
            "total_tokens": total_tokens if total_tokens is not None else "na",
            "preview": preview,
        }

    @staticmethod
    async def _run_completion(
        client: AsyncOpenAI,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.25,
            "max_tokens": max_tokens,
            "tool_choice": "none",
            "stream": False,
        }
        return await client.chat.completions.create(**kwargs)  # pyrefly: ignore[no-untyped-call]

    @staticmethod
    def _choice_payload(choice: Any) -> dict[str, Any]:
        if isinstance(choice, Mapping):
            return dict(choice)
        model_dump = getattr(choice, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped = None
            if isinstance(dumped, Mapping):
                return dict(dumped)
        model_dump_json = getattr(choice, "model_dump_json", None)
        if callable(model_dump_json):
            try:
                dumped_json = model_dump_json()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped_json = None
            if isinstance(dumped_json, str):
                try:
                    payload = json.loads(dumped_json)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, Mapping):
                    return dict(payload)
        return {}

    @classmethod
    def _coerce_text_candidate(cls, candidate: Any) -> str:
        if candidate is None:
            return ""
        if isinstance(candidate, str):
            return candidate.strip()
        if isinstance(candidate, Mapping):
            primary = candidate.get("content")
            text = cls._coerce_text_candidate(primary)
            if text:
                return text
            return cls._coerce_text_candidate(candidate.get("text"))
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            return cls._extract_message_content(candidate)
        content_attr = getattr(candidate, "content", None)
        if content_attr is not None:
            text = cls._coerce_text_candidate(content_attr)
            if text:
                return text
        text_attr = getattr(candidate, "text", None)
        if isinstance(text_attr, str):
            return text_attr.strip()
        if text_attr is not None:
            text = cls._coerce_text_candidate(text_attr)
            if text:
                return text
        model_dump = getattr(candidate, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
            except Exception:  # noqa: BLE001 - diagnostics only
                dumped = None
            if isinstance(dumped, Mapping):
                return cls._coerce_text_candidate(dumped.get("content") or dumped.get("text"))
        return cls._extract_message_content(candidate)

    @classmethod
    def _extract_text_from_choice(cls, payload: Mapping[str, Any]) -> str:
        if not isinstance(payload, Mapping):
            return ""
        message = payload.get("message")
        fragments = cls._collect_text_fragments(message)
        if fragments:
            return "\n".join(fragments)
        for key in ("content", "text"):
            candidate = payload.get(key)
            fragments = cls._collect_text_fragments(candidate)
            if fragments:
                return "\n".join(fragments)
        return ""

    @classmethod
    def _raw_choice_snapshot(cls, source: Any) -> tuple[str, str]:
        choice: Any = source
        if hasattr(source, "choices"):
            choices = getattr(source, "choices", None)
            if not choices:
                return "", ""
            choice = choices[0]
        payload = cls._choice_payload(choice)
        raw_keys = ",".join(sorted(payload.keys())) if payload else ""
        if payload:
            try:
                raw_repr = json.dumps(payload, ensure_ascii=False, default=str)
            except TypeError:
                raw_repr = str(payload)
        else:
            raw_repr = str(choice)
        snapshot = (raw_repr or "")[:200]
        return snapshot, raw_keys

    @classmethod
    def _extract_choice_content(cls, response: Any, *, client_id: int | None = None) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=True reason=no_choices")
            return ""
        first_choice = choices[0]
        raw_snapshot, raw_keys = cls._raw_choice_snapshot(first_choice)
        payload = cls._choice_payload(first_choice)
        extracted = cls._extract_text_from_choice(payload)
        message_obj: Any = (
            payload.get("message") if isinstance(payload, Mapping) else getattr(first_choice, "message", None)
        )
        tool_calls: Any | None = None
        if message_obj is None and isinstance(first_choice, Mapping):
            message_obj = first_choice.get("message")
        if message_obj is None:
            message_obj = getattr(first_choice, "message", None)
        if isinstance(message_obj, Mapping):
            tool_calls = message_obj.get("tool_calls")
        else:
            tool_calls = getattr(message_obj, "tool_calls", None)
        if extracted:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=False reason=message_content")
            return extracted
        if message_obj is None and isinstance(first_choice, Mapping):
            fallback_text = first_choice.get("content") or first_choice.get("text")
            if isinstance(fallback_text, str) and fallback_text.strip():
                if client_id is not None:
                    logger.debug("llm.parse client_id={} empty=False reason=choice_text".format(client_id))
                return fallback_text.strip()
        if isinstance(message_obj, Mapping):
            content = message_obj.get("content", "") or ""
        else:
            content = getattr(message_obj, "content", "") or ""
        secondary = cls._extract_message_content(content)
        if secondary:
            if client_id is not None:
                logger.debug(f"llm.parse client_id={client_id} empty=False reason=message_content")
            return secondary
        if tool_calls:
            for call in tool_calls:
                function = getattr(call, "function", None)
                arguments = getattr(function, "arguments", None)
                normalized = LLMHelper._normalize_tool_call_arguments(arguments)
                if normalized:
                    if client_id is not None:
                        logger.debug("llm.parse client_id={} empty=False reason=tool_call".format(client_id))
                    return normalized
        if raw_snapshot.strip() and client_id is not None:
            logger.debug(
                "llm.parse_mismatch client_id={} raw_first_200={} raw_keys={}".format(
                    client_id,
                    raw_snapshot,
                    raw_keys or "na",
                )
            )
        finish_reason = ""
        if choices:
            finish_reason = str(getattr(choices[0], "finish_reason", "") or "")
        if not extracted and client_id is not None and finish_reason == "length":
            logger.warning(
                "llm.parse empty_content client_id={} finish_reason=length keys={} snapshot={}".format(
                    client_id,
                    raw_keys or "na",
                    raw_snapshot,
                )
            )
        if client_id is not None:
            preview = LLMHelper._message_preview(message_obj)
            logger.debug(
                "llm.parse client_id={} empty=True reason=no_content finish_reason={} {}".format(
                    client_id,
                    finish_reason,
                    preview,
                )
            )
        return ""

    @staticmethod
    def _normalize_tool_call_arguments(arguments: Any) -> str:
        if arguments is None:
            return ""
        if isinstance(arguments, (bytes, bytearray)):
            raw_text = arguments.decode("utf-8", "ignore")
        elif isinstance(arguments, str):
            raw_text = arguments
        elif hasattr(arguments, "model_dump_json"):
            raw_text = arguments.model_dump_json()  # type: ignore[no-untyped-call]
        elif hasattr(arguments, "model_dump"):
            raw_text = json.dumps(arguments.model_dump())  # type: ignore[no-untyped-call]
        elif isinstance(arguments, dict):
            raw_text = json.dumps(arguments)
        else:
            raw_text = str(arguments)
        text = raw_text.strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            answer = str(payload.get("answer", "")).strip()
            raw_sources = payload.get("sources", [])
            sources: list[str] = []
            if isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes)):
                for item in raw_sources:
                    text_item = str(item).strip()
                    if text_item:
                        sources.append(text_item)
            sanitized = {"answer": answer, "sources": sources}
            return json.dumps(sanitized)
        return text

    @staticmethod
    def _message_preview(message: Any) -> str:
        if message is None:
            return "message=None"
        content = getattr(message, "content", None)
        preview_text = ""
        if isinstance(content, str):
            preview_text = content.strip()
        elif isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts = [str(item) for item in content if item]
            preview_text = " ".join(parts).strip()
        elif content:
            preview_text = str(content).strip()
        preview_text = preview_text.replace("\n", " ")
        if len(preview_text) > 120:
            preview_text = f"{preview_text[:117]}..."
        tool_calls = getattr(message, "tool_calls", None)
        tool_summary = "tool_calls=0"
        if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes)):
            names: list[str] = []
            for call in tool_calls:
                function = getattr(call, "function", None)
                name = getattr(function, "name", None)
                if name:
                    names.append(str(name))
            joined = ", ".join(names[:3])
            tool_summary = f"tool_calls={len(tool_calls)}[{joined}]" if joined else f"tool_calls={len(tool_calls)}"
        elif tool_calls:
            tool_summary = "tool_calls=1"
        preview_part = f"content_preview={preview_text!r}" if preview_text else "content_preview=''"
        return f"{preview_part} {tool_summary}"

    @staticmethod
    def _parse_fallback_content(
        content: str,
        entry_ids: Sequence[str],
        *,
        client_id: int,
    ) -> tuple[str, list[str]]:
        normalized_entries = [item for item in entry_ids if item]
        default_sources = list(normalized_entries) if normalized_entries else ["general_knowledge"]
        text = content.strip()
        if not text:
            return "", []
        should_parse_json = text.lstrip().startswith("{")
        if should_parse_json:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
                logger.warning(f"agent.ask fallback invalid_json client_id={client_id} error={exc}")
                should_parse_json = False
            else:
                answer = str(payload.get("answer", "")).strip()
                sources_payload = payload.get("sources", [])
                normalized_sources: list[str] = []
                if isinstance(sources_payload, Sequence) and not isinstance(sources_payload, (str, bytes)):
                    for item in sources_payload:
                        text_item = str(item).strip()
                        if text_item:
                            normalized_sources.append(text_item)
                if normalized_sources:
                    valid = {entry for entry in normalized_entries}
                    normalized_sources = [item for item in normalized_sources if item in valid]
                else:
                    normalized_sources = list(normalized_entries)
                candidate_sources = normalized_sources or default_sources
                if answer:
                    return answer, candidate_sources
                fallback_keys = ("response", "result", "text", "content", "message")
                for key in fallback_keys:
                    candidate = payload.get(key)
                    candidate_text = str(candidate).strip() if isinstance(candidate, str) else ""
                    if candidate_text:
                        logger.debug(
                            "agent.ask fallback_json_field client_id={} field={} len={}".format(
                                client_id,
                                key,
                                len(candidate_text),
                            )
                        )
                        return candidate_text, candidate_sources
        return text, default_sources

    @classmethod
    def _finalize_response(
        cls,
        response: QAResponse,
        entry_ids: Sequence[str],
        datasets: Sequence[str] | None,
        deps: AgentDeps | None = None,
    ) -> QAResponse:
        answer = response.answer.strip()
        if not answer:
            if deps is not None:
                deps.fallback_used = True
            raise AgentExecutionAborted("Model returned empty response", reason="model_empty_response")
        response.answer = answer
        dataset_sources = unique_sources(datasets or [])
        if dataset_sources:
            response.sources = dataset_sources
        else:
            valid_sources = set(entry_ids)
            if response.sources:
                filtered = [source for source in response.sources if source in valid_sources]
                if not filtered and entry_ids:
                    filtered = list(entry_ids)
                response.sources = filtered or ["general_knowledge"]
            else:
                response.sources = list(entry_ids) if entry_ids else ["general_knowledge"]
        return response

    @classmethod
    async def llm_probe(cls) -> dict[str, Any]:
        agent = cls._get_agent()
        cls._ensure_llm_logging(agent)
        model = getattr(agent, "model", None)
        if model is None:
            raise RuntimeError("LLM model is not configured")
        client: AsyncOpenAI | None = getattr(model, "client", None)
        if client is None:
            raise RuntimeError("LLM client is not configured")
        start = perf_counter()
        try:
            response = await client.chat.completions.create(  # pyrefly: ignore[no-untyped-call]
                model=settings.AGENT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a diagnostics probe."},
                    {"role": "user", "content": "Say: OK"},
                ],
                temperature=0.0,
                max_tokens=32,
                tool_choice="none",
            )
        except Exception as exc:  # noqa: BLE001
            latency = (perf_counter() - start) * 1000.0
            logger.warning(
                f"llm.probe_failed model={cls._model_identifier(model)} latency_ms={latency:.0f} error={exc}"
            )
            raise
        latency = (perf_counter() - start) * 1000.0
        choices = getattr(response, "choices", None) or []
        first_choice = choices[0] if choices else None
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", "") or ""
        tool_calls = getattr(message, "tool_calls", None)
        finish_reason = getattr(first_choice, "finish_reason", None) if first_choice else None
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        logger.debug(
            ("llm.probe model={} content_len={} has_tool_calls={} finish_reason={} latency_ms={:.0f}").format(
                cls._model_identifier(model),
                len(str(content).strip()),
                bool(tool_calls),
                finish_reason or "",
                latency,
            )
        )
        return {
            "model": cls._model_identifier(model),
            "content_length": len(str(content).strip()),
            "has_tool_calls": bool(tool_calls),
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": round(latency, 2),
        }
