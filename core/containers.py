from typing import Any

import httpx
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from dependency_injector import containers, providers

from config.app_settings import settings
from core.cache import Cache
from core.infra.payment_repository import HTTPPaymentRepository
from core.infra.profile_repository import HTTPProfileRepository
from core.payment import PaymentProcessor, PaymentService
from core.payment.types import CoachResolver, CreditService, PaymentNotifier
from core.services.internal.ai_coach_service import AiCoachService
from core.services.internal.profile_service import ProfileService
from core.services.internal.workout_service import WorkoutService


def build_http_client(**_: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.API_TIMEOUT,
        limits=httpx.Limits(
            max_connections=settings.API_MAX_CONNECTIONS,
            max_keepalive_connections=settings.API_MAX_KEEPALIVE_CONNECTIONS,
        ),
    )


async def close_http_client(client: httpx.AsyncClient) -> None:
    await client.aclose()


class App(containers.DeclarativeContainer):
    config = providers.Configuration()

    http_client = providers.Resource(build_http_client, shutdown=close_http_client)

    profile_repository = providers.Factory(HTTPProfileRepository, client=http_client, settings=settings)
    payment_repository = providers.Factory(HTTPPaymentRepository, client=http_client, settings=settings)
    profile_service = providers.Factory(ProfileService, repository=profile_repository)
    payment_service = providers.Factory(PaymentService, repository=payment_repository, settings=settings)
    workout_service = providers.Factory(WorkoutService, client=http_client, settings=settings)
    ai_coach_service = providers.Factory(AiCoachService, client=http_client, settings=settings)

    credit_service = providers.Dependency(instance_of=CreditService)
    coach_resolver = providers.Dependency(instance_of=CoachResolver)
    notifier = providers.Dependency(instance_of=PaymentNotifier)

    payment_processor = providers.Singleton(
        PaymentProcessor,
        cache=Cache,
        payment_service=payment_service,
        profile_service=profile_service,
        workout_service=workout_service,
        notifier=notifier,
        credit_service=credit_service,
        coach_resolver=coach_resolver,
    )

    bot = providers.Singleton(
        Bot,
        token=config.bot_token,
        default=providers.Callable(DefaultBotProperties, parse_mode=config.parse_mode),
    )


_container: App | None = None


def create_container() -> App:
    return App()


def set_container(container: App) -> None:
    global _container
    _container = container


def get_container() -> App:
    if _container is None:
        raise RuntimeError("Container is not initialized")
    return _container
