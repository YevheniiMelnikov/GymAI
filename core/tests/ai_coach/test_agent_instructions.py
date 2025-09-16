from ai_coach.agent.prompts import agent_instructions


def test_agent_instructions_program_subset() -> None:
    text = agent_instructions("program")
    assert "MODE: program" in text
    assert "MODE: subscription" not in text


def test_agent_instructions_ask_ai_subset() -> None:
    text = agent_instructions("ask_ai")
    assert "MODE: ask_ai" in text
    assert "tool_save_program" not in text
