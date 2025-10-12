from types import SimpleNamespace

import pytest

from ai_coach.agent import AgentDeps
from ai_coach.agent.tools import _single_use_prepare
from ai_coach.types import CoachMode


@pytest.mark.asyncio
async def test_subscription_tool_disabled_for_program_mode() -> None:
    deps = AgentDeps(client_id=1)
    deps.mode = CoachMode.program
    ctx = SimpleNamespace(deps=deps)
    prepare = _single_use_prepare("tool_create_subscription")
    dummy_tool = object()

    result = await prepare(ctx, dummy_tool)

    assert result is None
    assert "tool_create_subscription" in deps.disabled_tools


@pytest.mark.asyncio
async def test_subscription_tool_allowed_for_subscription_mode() -> None:
    deps = AgentDeps(client_id=1)
    deps.mode = CoachMode.subscription
    ctx = SimpleNamespace(deps=deps)
    prepare = _single_use_prepare("tool_create_subscription")
    dummy_tool = object()

    result = await prepare(ctx, dummy_tool)

    assert result is dummy_tool
