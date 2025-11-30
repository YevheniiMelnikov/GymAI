import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.security import HTTPBasic


from loguru import logger

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.cognee_config import CogneeConfig, ensure_cognee_ready
from dependency_injector import providers
from ai_coach.logging_config import configure_logging
from ai_coach.agent.knowledge.context import set_current_kb
from config.app_settings import settings
from core.internal_http import resolve_hmac_credentials

from core.containers import create_container, set_container, get_container
from core.infra.payment import TaskPaymentNotifier
from core.services.internal import APIService

configure_logging()

knowledge_ready_event: asyncio.Event | None = None


def _ensure_storage_path() -> None:
    storage_path = settings.COGNEE_STORAGE_PATH
    if not os.path.exists(storage_path):
        logger.error(f"Cognee storage path does not exist: {storage_path}")
        environment = getattr(settings, "ENVIRONMENT", None) or os.environ.get("ENVIRONMENT", "development")
        if environment != "production":
            os.makedirs(storage_path, exist_ok=True)
            logger.info(f"Created cognee storage path: {storage_path}")
        else:
            raise RuntimeError(f"Cognee storage path does not exist: {storage_path}")

    try:
        test_file_path = os.path.join(storage_path, ".write_test")
        with open(test_file_path, "w", encoding="utf-8") as handle:
            handle.write("test")
        os.remove(test_file_path)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Cognee storage path is not writable: {storage_path} ({exc})")
        raise RuntimeError(f"Cognee storage path is not writable: {storage_path} ({exc})") from exc


async def _bootstrap_global_dataset(kb: KnowledgeBase) -> tuple[bool, str]:
    user = getattr(kb, "_user", None)
    if user is None:
        user = await kb.dataset_service.get_cognee_user()
    loader = getattr(kb, "_loader", None)
    if loader is not None:
        try:
            await loader.load()
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            logger.debug(f"knowledge_loader_bootstrap_failed detail={exc}")
        if user is not None:
            try:
                await kb.projection_service.wait(kb.GLOBAL_DATASET, user, timeout=2.0)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"knowledge_bootstrap_projection_pending detail={exc}")
    ready_after_load, reason_after_load = await kb.projection_service.probe(kb.GLOBAL_DATASET, user)
    if ready_after_load or reason_after_load != "no_rows_in_dataset":
        return ready_after_load, reason_after_load
    if not settings.KB_BOOTSTRAP_ALWAYS:
        return ready_after_load, reason_after_load
    try:
        await kb.add_text(
            "KB initialized",
            dataset=kb.GLOBAL_DATASET,
            metadata={"kind": "note", "source": "bootstrap"},
            project=True,
        )
        if user is not None:
            await kb.projection_service.wait(kb.GLOBAL_DATASET, user, timeout=2.0)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"knowledge_bootstrap_seed_failed detail={exc}")
    return await kb.projection_service.probe(kb.GLOBAL_DATASET, user)


async def init_knowledge_base(kb: KnowledgeBase, knowledge_loader: KnowledgeLoader | None = None) -> None:
    """Initialize the knowledge base."""
    global knowledge_ready_event
    if knowledge_ready_event is None:
        knowledge_ready_event = asyncio.Event()

    if knowledge_ready_event.is_set():
        return

    try:
        await kb.initialize(knowledge_loader)
    except Exception as e:  # pragma: no cover - best effort
        logger.error(f"AI coach init failed: {e}")
        knowledge_ready_event.clear()
        raise

    projection_ready_status = ProjectionStatus.FATAL_ERROR
    configured_timeout = float(settings.AI_COACH_GLOBAL_PROJECTION_TIMEOUT)
    projection_timeout = max(configured_timeout, 45.0)
    probe_ready = False
    probe_reason = "unknown"
    try:
        probe_ready, probe_reason = await kb.projection_service.probe(kb.GLOBAL_DATASET, kb._user)
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        logger.warning(f"AI coach projection probe failed: {exc}")

    if probe_ready:
        projection_ready_status = ProjectionStatus.READY
        logger.info("knowledge_dataset_cognify_ok dataset=kb_global")
    elif probe_reason == "no_rows_in_dataset":
        bootstrap_ready, bootstrap_reason = await _bootstrap_global_dataset(kb)
        if bootstrap_ready:
            projection_ready_status = ProjectionStatus.READY
            logger.info("knowledge_dataset_cognify_ok dataset=kb_global")
        elif bootstrap_reason == "no_rows_in_dataset":
            projection_ready_status = ProjectionStatus.READY_EMPTY
            kb.dataset_service.log_once(
                logging.INFO,
                "projection:skip_no_rows",
                dataset=kb.GLOBAL_DATASET,
                stage="startup",
                min_interval=120.0,
            )
            logger.debug("projection:skip_no_rows dataset=kb_global stage=startup")
        else:
            projection_ready_status = await kb.projection_service.wait(
                kb.GLOBAL_DATASET,
                kb._user,
                timeout=projection_timeout,
            )
            if projection_ready_status == ProjectionStatus.READY:
                logger.info("knowledge_dataset_cognify_ok dataset=kb_global")
            elif projection_ready_status == ProjectionStatus.READY_EMPTY:
                kb.dataset_service.log_once(
                    logging.INFO,
                    "projection:skip_no_rows",
                    dataset=kb.GLOBAL_DATASET,
                    stage="startup",
                    min_interval=120.0,
                )
                logger.debug("projection:skip_no_rows dataset=kb_global stage=startup")
    else:
        try:
            projection_ready_status = await kb.projection_service.wait(
                kb.GLOBAL_DATASET,
                kb._user,
                timeout=projection_timeout,
            )
            if projection_ready_status == ProjectionStatus.READY:
                logger.info("knowledge_dataset_cognify_ok dataset=kb_global")
            elif projection_ready_status == ProjectionStatus.READY_EMPTY:
                kb.dataset_service.log_once(
                    logging.INFO,
                    "projection:skip_no_rows",
                    dataset=kb.GLOBAL_DATASET,
                    stage="startup",
                    min_interval=120.0,
                )
                logger.debug("projection:skip_no_rows dataset=kb_global stage=startup")
        except Exception as exc:  # noqa: BLE001 - best-effort diagnostics
            logger.warning(f"AI coach projection wait failed: {exc}")
            projection_ready_status = ProjectionStatus.FATAL_ERROR
    if projection_ready_status in (ProjectionStatus.READY, ProjectionStatus.READY_EMPTY):
        logger.success("AI coach initialized")
    else:
        logger.warning(
            f"AI coach global dataset not projected within {projection_timeout:.1f}s, "
            f"status: {projection_ready_status.value}"
        )

        async def _await_projection() -> None:
            try:
                ready_status = await kb.projection_service.wait(
                    kb.GLOBAL_DATASET,
                    kb._user,
                    timeout=projection_timeout,
                )
            except Exception as wait_exc:  # noqa: BLE001
                logger.warning(f"AI coach delayed projection wait failed: {wait_exc}")
                return
            if ready_status == ProjectionStatus.READY and knowledge_ready_event is not None:
                logger.info("knowledge_dataset_cognify_ok dataset=kb_global")
                logger.info("AI coach global dataset projection ready after delay")
            elif ready_status == ProjectionStatus.READY_EMPTY and knowledge_ready_event is not None:
                logger.debug("projection:skip_no_rows dataset=kb_global stage=startup")

        if probe_reason != "no_rows_in_dataset":
            asyncio.create_task(_await_projection())

    knowledge_ready_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from ai_coach.agent.knowledge.gdrive_knowledge_loader import GDriveDocumentLoader

    env_mode = str(getattr(settings, "ENVIRONMENT", "development")).lower()
    creds = resolve_hmac_credentials(settings, prefer_ai_coach=True)
    if creds is None:
        if env_mode == "production":
            raise RuntimeError("AI coach HMAC credentials are not configured")
        logger.warning("AI coach HMAC credentials are not configured; running without HMAC in non-production mode")

    _ensure_storage_path()

    container = create_container()
    container.notifier.override(providers.Factory(TaskPaymentNotifier))
    set_container(container)
    APIService.configure(get_container)
    container.wire(modules=["core.tasks.ai_coach"])
    init_resources = container.init_resources()
    if init_resources is not None:
        await init_resources

    CogneeConfig.apply()
    await ensure_cognee_ready()

    kb = KnowledgeBase()
    set_current_kb(kb)
    app.state.kb = kb
    loader = GDriveDocumentLoader(kb)  # pyrefly: ignore[bad-instantiation]
    await init_knowledge_base(kb, loader)
    try:
        yield
    finally:
        shutdown_resources = container.shutdown_resources()
        if shutdown_resources is not None:
            await shutdown_resources
        set_current_kb(None)
        app.state.kb = None


app = FastAPI(title="AI Coach", lifespan=lifespan)
security = HTTPBasic()
