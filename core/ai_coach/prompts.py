SYSTEM_MESSAGE = (
    "You are an experienced fitness coach. Use your expert knowledge, client "
    "history, and structured data to generate an individualized gym workout "
    "plan."
)

PROGRAM_PROMPT = """
Input:
{{
  "client_profile": {client_profile},
  "previous_program": {previous_program},
  "request": {request}
}}

Instructions:
- Include an estimated working weight for each weighted exercise where possible.
- Respond strictly in the client's language: {language}
- Return only valid JSON compatible with the ProgramResponse Pydantic model.
- The reply MUST start with '{{' and end with '}}' — no extra text.
"""

SUBSCRIPTION_PROMPT = """
    Using the stored client information and chat context, create a training plan
    tailored to the request below.
    Workout type: {workout_type}. Client wishes: {wishes}. Preferred workout days: {workout_days}.
    Respond exclusively in the client's language: {language}. Use this language for all text.
    Respond strictly with JSON that matches 
    the `SubscriptionResponse` Pydantic model. The reply MUST contain only valid JSON 
    starting with '{{' and ending with '}}' and no extra text.
    Request:
    {request}
    Example response:
    {{
      "workout_days": ["monday", "wednesday"],
      "exercises": [
        {{"day": "monday", "exercises": [{{"name": "Dumbbell Rows", "sets": "3", "reps": "12", "weight": "20"}}]}}
      ]
    }}
"""

INITIAL_PROMPT = """
    Memorize the following client profile information and use it as context for all future responses.
    {client_data}
"""
