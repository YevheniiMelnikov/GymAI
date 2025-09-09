from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def _load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


COACH_SYSTEM_PROMPT: str = _load_template("system_prompt.txt")
AGENT_INSTRUCTIONS: str = _load_template("agent_instructions.txt")
COACH_INSTRUCTIONS: str = _load_template("coach_instructions.txt")
GENERATE_WORKOUT: str = _load_template("generate_workout.txt")
UPDATE_WORKOUT: str = _load_template("update_workout.txt")

__all__ = [
    "COACH_SYSTEM_PROMPT",
    "AGENT_INSTRUCTIONS",
    "COACH_INSTRUCTIONS",
    "GENERATE_WORKOUT",
    "UPDATE_WORKOUT",
]
