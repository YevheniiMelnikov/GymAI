import pytest

from core.ai_plan_state import AiPlanState
from redis.asyncio import Redis


@pytest.mark.asyncio
async def test_claim_delivery_once() -> None:
    state = AiPlanState(Redis())
    assert await state.claim_delivery("req-1", ttl_s=1)
    assert not await state.claim_delivery("req-1", ttl_s=1)


@pytest.mark.asyncio
async def test_mark_delivered_and_failed() -> None:
    state = AiPlanState(Redis())
    await state.mark_delivered("req-2", ttl_s=1)
    assert await state.is_delivered("req-2")

    assert await state.mark_failed("req-3", "error", ttl_s=1)
    assert not await state.mark_failed("req-3", "other", ttl_s=1)
    assert await state.is_failed("req-3")
