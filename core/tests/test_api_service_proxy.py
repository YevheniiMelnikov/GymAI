import asyncio

from core.services.internal import APIService


class DummyService:
    async def ping(self) -> str:
        return "pong"


class DummyContainer:
    def __init__(self, factory):
        self.profile_service = factory


def test_async_provider() -> None:
    async def runner() -> None:
        async def factory() -> DummyService:
            return DummyService()

        APIService.configure(lambda: DummyContainer(factory))
        assert await APIService.profile.ping() == "pong"

    asyncio.run(runner())


def test_sync_provider() -> None:
    async def runner() -> None:
        def factory() -> DummyService:
            return DummyService()

        APIService.configure(lambda: DummyContainer(factory))
        assert await APIService.profile.ping() == "pong"

    asyncio.run(runner())
