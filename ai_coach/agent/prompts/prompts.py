from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def _load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


COACH_SYSTEM_PROMPT: str = _load_template("system_prompt.txt")
COACH_INSTRUCTIONS: str = _load_template("coach_instructions.txt")
GENERATE_WORKOUT: str = _load_template("generate_workout.txt")
UPDATE_WORKOUT: str = _load_template("update_workout.txt")
ASK_AI_USER_PROMPT: str = _load_template("ask_ai_user_prompt.txt")
CHAT_SUMMARY_PROMPT: str = _load_template("chat_summary.txt")
REPLACE_EXERCISE_PROMPT: str = _load_template("replace_exercise.txt")

_AGENT_COMMON: str = _load_template("agent_common.txt")
_AGENT_PROGRAM: str = _load_template("agent_program.txt")
_AGENT_SUBSCRIPTION: str = _load_template("agent_subscription.txt")
_AGENT_UPDATE: str = _load_template("agent_update.txt")
_AGENT_ASK_AI: str = _load_template("agent_ask_ai.txt")
_AGENT_DIET: str = _load_template("agent_diet.txt")
DIET_PLAN: str = _load_template("diet_plan.txt")


def _strip_knowledge_instructions(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        lowered = line.lower()
        if "tool_search_knowledge" in lowered:
            continue
        if "knowledge base" in lowered:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def agent_instructions(mode: str, *, kb_enabled: bool = True) -> str:
    mapping = {
        "program": _AGENT_PROGRAM,
        "subscription": _AGENT_SUBSCRIPTION,
        "update": _AGENT_UPDATE,
        "ask_ai": _AGENT_ASK_AI,
        "diet": _AGENT_DIET,
    }
    try:
        common = _AGENT_COMMON
        mode_text = mapping[mode]
        if not kb_enabled:
            common = _strip_knowledge_instructions(common)
            mode_text = _strip_knowledge_instructions(mode_text)
            return f"{common}\n{mode_text}\nKnowledge base is disabled. Do not call tool_search_knowledge."
        return f"{common}\n{mode_text}"
    except KeyError as e:
        raise KeyError(f"Unknown mode: {mode}") from e


__all__ = [
    "COACH_SYSTEM_PROMPT",
    "COACH_INSTRUCTIONS",
    "GENERATE_WORKOUT",
    "UPDATE_WORKOUT",
    "ASK_AI_USER_PROMPT",
    "CHAT_SUMMARY_PROMPT",
    "REPLACE_EXERCISE_PROMPT",
    "DIET_PLAN",
    "agent_instructions",
]
