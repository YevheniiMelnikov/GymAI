PROGRAM_PROMPT = (
    "You are an experienced fitness coach. Use your knowledge base, previous "
    "dialogue history and the saved client profile to craft a workout program.\n"
    "Workout type: {workout_type}. Client wishes: {wishes}\n"
    "Respond exclusively in the client's language: {language}. Use this language for all text.\n"
    "Include an estimated working weight for each weighted exercise when possible.\n"
    "The request parameters are provided as JSON below. Respond strictly with "
    "JSON compatible with the `ProgramResponse` Pydantic model.\n"
    "Request:\n{request}\n"
    "Example response:\n"
    "{{\n"
    '  "days": [\n'
    '    {{"day": "day_1", "exercises": [\n'
    '      {{"name": "Push ups", "sets": "3", "reps": "12"}}\n'
    "    ]}}\n"
    "  ]\n"
    "}}"
)

SUBSCRIPTION_PROMPT = (
    "Using the stored client information and chat context, create a training plan"
    " tailored to the request below.\n"
    "Workout type: {workout_type}. Client wishes: {wishes}. Preferred workout days: {workout_days}.\n"
    "Respond exclusively in the client's language: {language}. Use this language for all text.\n"
    "Respond strictly with JSON that matches "
    "the `SubscriptionResponse` Pydantic model.\n"
    "Request:\n{request}\n"
    "Example response:\n"
    "{{\n"
    '  "workout_days": ["monday", "wednesday"],\n'
    '  "exercises": [\n'
    '    {{"day": "monday", "exercises": [{{"name": "Squats", "sets": "3", "reps": "10"}}]}}\n'
    "  ]\n"
    "}}"
)
