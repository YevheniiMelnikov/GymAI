from types import SimpleNamespace

import pytest  # pyrefly: ignore[import-error]
from pydantic_ai import ModelRetry  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps
from ai_coach.agent.tools import tool_calculate_bmi


@pytest.mark.asyncio
async def test_tool_calculate_bmi_returns_expected_value() -> None:
    deps = AgentDeps(profile_id=1)
    ctx = SimpleNamespace(deps=deps)
    result = await tool_calculate_bmi(ctx, weight_kg=80.0, height_cm=180.0)
    assert result == {"bmi": 24.7, "weight_kg": 80.0, "height_cm": 180.0}


@pytest.mark.asyncio
async def test_tool_calculate_bmi_rejects_non_positive_values() -> None:
    deps = AgentDeps(profile_id=1)
    ctx = SimpleNamespace(deps=deps)
    with pytest.raises(ModelRetry):
        await tool_calculate_bmi(ctx, weight_kg=0.0, height_cm=180.0)
