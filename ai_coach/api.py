import os
from fastapi import Body, Depends, HTTPException  # pyrefly: ignore[import-error]
from fastapi.responses import JSONResponse  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]
from typing import Any, cast

from ai_coach.api_security import require_hmac as _require_hmac
from ai_coach.api_security import validate_refresh_credentials as _validate_refresh_credentials
from ai_coach import application as coach_application
from ai_coach.application import app, security
from ai_coach import ask_handler as _ask_handler
from ai_coach.agent import CoachAgent  # noqa: F401 - re-exported for tests
from ai_coach.agent.utils import get_knowledge_base
from ai_coach.coach_actions import DISPATCH  # noqa: F401 - re-exported for compatibility
from ai_coach.schemas import AICoachRequest
from ai_coach.types import CoachMode
from config.app_settings import settings
from core.exceptions import UserServiceError
from core.schemas import DietPlan, Program, QAResponse, Subscription
from pydantic import BaseModel

# Re-export compatibility symbols expected by tests/old clients
DEFAULT_SPLIT_NUMBER = _ask_handler.DEFAULT_SPLIT_NUMBER
dedupe_cache = _ask_handler.dedupe_cache
# Primary request handler
handle_coach_request = _ask_handler.handle_coach_request


@app.get("/health/")
async def health() -> dict[str, str]:
    knowledge_ready_event = coach_application.knowledge_ready_event
    if knowledge_ready_event is None or not knowledge_ready_event.is_set():
        raise HTTPException(status_code=503, detail="Knowledge base is not ready")
    if getattr(app.state, "kb", None) is None:
        raise HTTPException(status_code=503, detail="Knowledge base is not available")
    return {"status": "ok"}


@app.get("/health/kb")
async def health_kb() -> dict[str, Any]:
    kb = get_knowledge_base()
    storage_path = settings.COGNEE_STORAGE_PATH
    storage_ok = os.path.exists(storage_path) and os.access(storage_path, os.W_OK)
    user = getattr(kb, "_user", None)
    if user is None:
        user = await kb.dataset_service.get_cognee_user()
    try:
        projected, projection_reason = await kb.projection_service.probe(kb.GLOBAL_DATASET, user)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"kb_health.probe_failed detail={exc}")
        projected = False
        projection_reason = "fatal_error"
    dataset_registry_size = kb.dataset_service.get_dataset_alias_count()
    last_rebuild_info = kb.get_last_rebuild_result()
    return {
        "status": "ok" if storage_ok and projected else "error",
        "storage_access_ok": storage_ok,
        "projected": projected,
        "projection_reason": projection_reason,
        "dataset_registry_size": dataset_registry_size,
        "last_rebuild_info": last_rebuild_info,
    }


@app.get("/internal/debug/llm_probe")
async def debug_llm_probe(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    try:
        return await CoachAgent.llm_probe()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"/internal/debug/llm_probe failed: {exc}")
        raise HTTPException(status_code=503, detail="LLM probe failed") from exc


@app.get("/internal/debug/llm_echo")
async def debug_llm_echo(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, str]:
    _validate_refresh_credentials(credentials)
    client, model_name = CoachAgent._get_completion_client()
    CoachAgent._ensure_llm_logging(client, model_name)
    response = await CoachAgent._complete_with_retries(
        client,
        "Answer with one word: OK",
        "Echo-test",
        [],
        profile_id=0,
        max_tokens=32,
        model=model_name,
    )
    if response is None or not response.answer.strip():
        raise HTTPException(status_code=503, detail="LLM echo failed")
    return {"answer": response.answer.strip()}


@app.get("/internal/kb/dump")
async def kb_dump(
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    kb = get_knowledge_base()
    ds = kb.dataset_service
    user = getattr(kb, "_user", None) or await ds.get_cognee_user()
    global_alias = ds.alias_for_dataset("kb_global")
    global_ident = ds.get_registered_identifier("kb_global")
    global_effective = global_ident or global_alias
    global_counts = await ds.get_counts(global_effective, user=user)

    chat_alias = ds.alias_for_dataset(ds.chat_dataset_name(1))
    chat_ident = ds.get_registered_identifier(chat_alias)
    chat_effective = chat_ident or chat_alias
    chat_counts = await ds.get_counts(chat_effective, user=user)

    projected_global = kb.get_projection_health(global_alias)
    projected_chat = kb.get_projection_health(chat_alias)
    return {
        "kb_global": {
            "alias": global_alias,
            "identifier": global_ident,
            "effective": global_effective,
            "counts": global_counts,
        },
        "kb_chat_1": {
            "alias": chat_alias,
            "identifier": chat_ident,
            "effective": chat_effective,
            "counts": chat_counts,
        },
        "ident_map": ds.dump_identifier_map(),
        "projection": {
            "kb_global": projected_global,
            "kb_chat_1": projected_chat,
        },
        "last_reingest": kb.get_last_rebuild_result(),
    }


@app.get("/internal/kb/audit")
async def kb_audit(
    datasets: str,
    credentials: HTTPBasicCredentials = Depends(security),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    _validate_refresh_credentials(credentials)
    kb = get_knowledge_base()
    ds = kb.dataset_service
    user = getattr(kb, "_user", None) or await ds.get_cognee_user()
    requested = [item.strip() for item in (datasets or "").split(",") if item.strip()]
    resolved: list[dict[str, Any]] = []
    for raw in requested:
        canonical = ds.resolve_dataset_alias(raw)
        identifier = ds.get_registered_identifier(canonical)
        effective = identifier or canonical
        counts = await ds.get_counts(effective, user)
        resolved.append(
            {
                "raw": raw,
                "canonical": canonical,
                "identifier": identifier,
                "effective": effective,
                "counts": counts,
            }
        )
    return {"requested": requested, "resolved": resolved}


@app.post("/coach/plan/", response_model=Program | Subscription | list[str] | None)
async def coach_plan(
    data: AICoachRequest,
    _: None = Depends(_require_hmac),
) -> Program | Subscription | list[str] | None | JSONResponse:
    allowed_modes = {CoachMode.program, CoachMode.subscription, CoachMode.update}
    result = await handle_coach_request(data, allowed_modes=allowed_modes)
    return cast(JSONResponse | Program | Subscription | list[str] | None, result)


@app.post("/coach/chat/", response_model=QAResponse | None)
async def coach_chat(
    data: AICoachRequest,
    _: None = Depends(_require_hmac),
) -> QAResponse | JSONResponse | None:
    if data.mode != CoachMode.ask_ai:
        raise HTTPException(status_code=422, detail="chat endpoint accepts only ask_ai mode")
    return cast(QAResponse | JSONResponse | None, await handle_coach_request(data, allowed_modes={CoachMode.ask_ai}))


@app.post("/coach/diet/", response_model=DietPlan | None)
async def coach_diet(
    data: AICoachRequest,
    _: None = Depends(_require_hmac),
) -> DietPlan | JSONResponse | None:
    if data.mode != CoachMode.diet:
        raise HTTPException(status_code=422, detail="diet endpoint accepts only diet mode")
    return cast(DietPlan | JSONResponse | None, await handle_coach_request(data, allowed_modes={CoachMode.diet}))


@app.post("/knowledge/refresh/")
async def refresh_knowledge(
    force: bool = False,
    credentials: HTTPBasicCredentials = Depends(_validate_refresh_credentials),
) -> dict[str, str]:
    """Refresh the knowledge base."""
    kb = get_knowledge_base()
    try:
        await kb.refresh(force=force)
        logger.info("knowledge_refresh_triggered")
        return {"status": "ok"}
    except Exception as exc:
        logger.exception(f"knowledge_refresh_failed detail={exc}")
        raise HTTPException(status_code=503, detail="Refresh failed") from exc


async def _execute_prune() -> dict[str, str]:
    try:
        kb = get_knowledge_base()
        await kb.prune()
    except UserServiceError as exc:
        logger.error(f"Knowledge prune failed: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Knowledge prune failed unexpectedly: {exc}")
        raise HTTPException(status_code=503, detail="Cognee prune failed") from exc

    return {"status": "ok"}


@app.post("/internal/knowledge/prune/")
async def prune_knowledge_base_internal(_: None = Depends(_require_hmac)) -> dict[str, str]:
    return await _execute_prune()


@app.post("/knowledge/prune/")
async def prune_knowledge_base(_: None = Depends(_require_hmac)):
    return await _execute_prune()


class ProfileSyncRequest(BaseModel):
    reason: str | None = None


class ProfileMemifyRequest(BaseModel):
    reason: str | None = None


async def _cleanup_profile(profile_id: int) -> dict[str, Any]:
    kb = get_knowledge_base()
    result = await kb.cleanup_profile_datasets(profile_id)
    logger.debug(
        "profile_cleanup_request profile_id={} datasets={}",
        profile_id,
        ",".join(result.keys()),
    )
    return {"profile_id": profile_id, "result": result}


@app.post("/internal/knowledge/profiles/{profile_id}/cleanup/")
async def cleanup_profile_knowledge_internal(
    profile_id: int,
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    return await _cleanup_profile(profile_id)


@app.post("/knowledge/profiles/{profile_id}/cleanup/")
async def cleanup_profile_knowledge_public(
    profile_id: int,
    credentials: HTTPBasicCredentials = Depends(_validate_refresh_credentials),
) -> dict[str, Any]:
    return await _cleanup_profile(profile_id)


async def _sync_profile(profile_id: int, payload: ProfileSyncRequest | None = None) -> dict[str, Any]:
    if not settings.AI_COACH_KB_ENABLED:
        logger.info(
            "profile_sync_skipped profile_id={} reason={} detail=kb_disabled",
            profile_id,
            payload.reason if payload else None,
        )
        return {"profile_id": profile_id, "indexed": False}
    kb = get_knowledge_base()
    indexed = await kb.sync_profile_dataset(profile_id)
    logger.info(
        "profile_sync_request profile_id={} indexed={} reason={}",
        profile_id,
        indexed,
        payload.reason if payload else None,
    )
    return {"profile_id": profile_id, "indexed": bool(indexed)}


@app.post("/internal/knowledge/profiles/{profile_id}/sync/")
async def sync_profile_knowledge_internal(
    profile_id: int,
    payload: ProfileSyncRequest = Body(default_factory=ProfileSyncRequest),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    return await _sync_profile(profile_id, payload)


@app.post("/knowledge/profiles/{profile_id}/sync/")
async def sync_profile_knowledge_public(
    profile_id: int,
    payload: ProfileSyncRequest = Body(default_factory=ProfileSyncRequest),
    credentials: HTTPBasicCredentials = Depends(_validate_refresh_credentials),
) -> dict[str, Any]:
    return await _sync_profile(profile_id, payload)


async def _memify_profile(profile_id: int, payload: ProfileMemifyRequest | None = None) -> dict[str, Any]:
    kb = get_knowledge_base()
    result = await kb.memify_profile_datasets(profile_id)
    logger.info(
        "profile_memify_request profile_id={} datasets={} reason={}",
        profile_id,
        ",".join(result.get("datasets", []) or []),
        payload.reason if payload else None,
    )
    return {"profile_id": profile_id, "result": result}


@app.post("/internal/knowledge/profiles/{profile_id}/memify/")
async def memify_profile_datasets_internal(
    profile_id: int,
    payload: ProfileMemifyRequest = Body(default_factory=ProfileMemifyRequest),
    _: None = Depends(_require_hmac),
) -> dict[str, Any]:
    return await _memify_profile(profile_id, payload)


@app.post("/knowledge/profiles/{profile_id}/memify/")
async def memify_profile_datasets_public(
    profile_id: int,
    payload: ProfileMemifyRequest = Body(default_factory=ProfileMemifyRequest),
    credentials: HTTPBasicCredentials = Depends(_validate_refresh_credentials),
) -> dict[str, Any]:
    return await _memify_profile(profile_id, payload)
