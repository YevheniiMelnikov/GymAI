from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def _load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


COACH_SYSTEM_PROMPT = _load_template("coach_system_prompt.txt")
WORKOUT_RULES = _load_template("workout_rules.txt")
WORKOUT_PLAN_PROMPT = _load_template("workout_plan_prompt.txt")
UPDATE_WORKOUT_PROMPT = _load_template("update_workout_prompt.txt")

__all__ = [
    "COACH_SYSTEM_PROMPT",
    "WORKOUT_RULES",
    "WORKOUT_PLAN_PROMPT",
    "UPDATE_WORKOUT_PROMPT",
]
