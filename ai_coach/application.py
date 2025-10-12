import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.security import HTTPBasic


from loguru import logger

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from dependency_injector import providers

from core.containers import create_container, set_container, get_container
from core.infra.payment import BotCoachResolver, BotCreditService, TaskPaymentNotifier
from core.services.internal import APIService


logging.getLogger("OntologyAdapter").setLevel(logging.WARNING)
logging.getLogger("CogneeGraph").setLevel(logging.ERROR)

knowledge_ready_event: asyncio.Event | None = None


async def init_knowledge_base(knowledge_loader: KnowledgeLoader | None = None) -> None:
    """Initialize the knowledge base."""
    global knowledge_ready_event
    if knowledge_ready_event is None:
        knowledge_ready_event = asyncio.Event()

    if knowledge_ready_event.is_set():
        return

    try:
        await KnowledgeBase.initialize(knowledge_loader)
    except Exception as e:  # pragma: no cover - best effort
        logger.error(f"AI coach init failed: {e}")
        knowledge_ready_event.clear()
        raise

    logger.success("AI coach initialized")
    knowledge_ready_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from ai_coach.agent.knowledge.gdrive_knowledge_loader import GDriveDocumentLoader

    container = create_container()
    container.notifier.override(providers.Factory(TaskPaymentNotifier))
    container.credit_service.override(providers.Factory(BotCreditService))
    container.coach_resolver.override(providers.Factory(BotCoachResolver))
    set_container(container)
    APIService.configure(get_container)
    container.wire(modules=["core.tasks"])
    init_resources = container.init_resources()
    if init_resources is not None:
        await init_resources

    loader = GDriveDocumentLoader(KnowledgeBase.add_text)
    await init_knowledge_base(loader)
    try:
        yield
    finally:
        shutdown_resources = container.shutdown_resources()
        if shutdown_resources is not None:
            await shutdown_resources


app = FastAPI(title="AI Coach", lifespan=lifespan)
security = HTTPBasic()
