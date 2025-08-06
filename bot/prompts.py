from importlib import resources


def _load_template(name: str) -> str:
    return resources.files("bot.prompt_templates").joinpath(name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_template("system_prompt.txt")
WORKOUT_RULES = _load_template("workout_rules.txt")
WORKOUT_PLAN_PROMPT = _load_template("workout_plan_prompt.txt")
PROGRAM_RESPONSE_TEMPLATE = _load_template("program_response.json")
SUBSCRIPTION_RESPONSE_TEMPLATE = _load_template("subscription_response.json")

INITIAL_PROMPT = """
    Memorize the following client profile information and use it as context for all future responses.
    {client_data}
    Always respond strictly in the client's language: {language}
"""

UPDATE_WORKOUT_PROMPT = """
    Your task is to update a client's workout plan based on:

    1. The workout that was originally expected from the client.
    2. The feedback the client provided after performing that workout.
    3. Additional context from the client’s past training history or program notes.

    --- Expected Workout ---
    {expected_workout}

    --- Client Feedback ---
    {feedback}

    --- Context ---
    {context}

    Instructions:
    - Carefully analyze the differences between the expected workout and the client’s feedback.
    - Use the context to understand what might need adjusting long-term (e.g., overuse, pain, progress, boredom).
    - Update the workout plan accordingly:
      - You may adjust exercises, reps, sets, weights, or training days.
      - Keep useful structure from the current plan unless the feedback suggests otherwise.
      - Respect injuries, fatigue, or strong preferences.
      - Keep output compact and relevant.

    Respond strictly in the client's language: {language}
    Only return the updated plan. Do not include commentary or explanations.
"""
