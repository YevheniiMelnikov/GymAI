from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def _load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


COACH_SYSTEM_PROMPT: str = _load_template("system_prompt.txt")
COACH_INSTRUCTIONS: str = _load_template("coach_instructions.txt")
GENERATE_WORKOUT: str = _load_template("generate_workout.txt")
UPDATE_WORKOUT: str = _load_template("update_workout.txt")
ASK_AI_USER_PROMPT: str = _load_template("ask_ai_user_prompt.txt")

_AGENT_COMMON: str = _load_template("agent_common.txt")
_AGENT_PROGRAM: str = _load_template("agent_program.txt")
_AGENT_SUBSCRIPTION: str = _load_template("agent_subscription.txt")
_AGENT_UPDATE: str = _load_template("agent_update.txt")
_AGENT_ASK_AI: str = _load_template("agent_ask_ai.txt")


def agent_instructions(mode: str) -> str:
    mapping = {
        "program": _AGENT_PROGRAM,
        "subscription": _AGENT_SUBSCRIPTION,
        "update": _AGENT_UPDATE,
        "ask_ai": _AGENT_ASK_AI,
    }
    try:
        return f"{_AGENT_COMMON}\n{mapping[mode]}"
    except KeyError as e:
        raise KeyError(f"Unknown mode: {mode}") from e


__all__ = [
    "COACH_SYSTEM_PROMPT",
    "COACH_INSTRUCTIONS",
    "GENERATE_WORKOUT",
    "UPDATE_WORKOUT",
    "ASK_AI_USER_PROMPT",
    "agent_instructions",
]
