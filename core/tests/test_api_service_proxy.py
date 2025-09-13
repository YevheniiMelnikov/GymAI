import asyncio

from core.services.internal import APIService


class DummyService:
    async def ping(self) -> str:
        return "pong"


class DummyContainer:
    def __init__(self, factory):
        self.profile_service = factory


def test_async_provider() -> None:
    async def factory():
        return DummyService()

    APIService.configure(lambda: DummyContainer(factory))
    assert asyncio.run(APIService.profile.ping()) == "pong"


def test_sync_provider() -> None:
    def factory():
        return DummyService()

    APIService.configure(lambda: DummyContainer(factory))
    assert asyncio.run(APIService.profile.ping()) == "pong"
