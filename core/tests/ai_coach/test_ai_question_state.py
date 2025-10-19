import asyncio

from core.ai_coach import AiQuestionState
from redis.asyncio import Redis


def test_claim_task_and_delivery_are_independent() -> None:
    state = AiQuestionState(Redis())

    async def scenario() -> None:
        assert await state.claim_task("req-1", ttl_s=1)
        assert await state.claim_delivery("req-1", ttl_s=1)
        assert not await state.claim_delivery("req-1", ttl_s=1)
        assert not await state.claim_task("req-1", ttl_s=1)

    asyncio.run(scenario())
