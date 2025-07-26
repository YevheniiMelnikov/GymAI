SYSTEM_MESSAGE = """
    You are an experienced fitness coach. Use your expert knowledge, client 
    history, and structured data to generate an individualized gym workout plan.
"""

PROGRAM_PROMPT = """
    Request:
    {{
      "client_profile": {client_profile},
      "previous_program": {previous_program},
      "request": {request}
    }}
    
    Instructions:
    - Include an estimated working weight (kg) for each weighted exercise where possible.
    - Respond strictly in the client's language: {language}
    - Return only valid JSON compatible with the example bellow.
    - The reply MUST start with '{{' and end with '}}' — no extra text.
    
    Example response:
    {{
      "exercises_by_day": [
        {
          "day": "day_1",
          "exercises": [
            {
              "name": "Bench Press",
              "sets": "4",
              "reps": "8",
              "gif_link": None,  // put the 'None' here
              "weight": "80",  // kg
              "set_id": None,  // use it to combine exercises into sets
              "drop_set": false
            },
            {
              "name": "Incline Dumbbell Press",
              "sets": "3",
              "reps": "10",
              "gif_link": None,
              "weight": "24",
              "set_id": None,
              "drop_set": false
            }
          ]
        }
      ]
    }}
"""

SUBSCRIPTION_PROMPT = """
    Request:
    {{
      "workout_type": "{workout_type}",
      "wishes": "{wishes}",
      "preferred_workout_days": {workout_days},
      "request": {request}
    }}
    
    Instructions:
    - Generate a workout plan distributed over the preferred workout days.
    - Include an estimated working weight (kg) for each weighted exercise where possible.
    - Respond strictly in the client's language: {language}
    - Return only valid JSON compatible with the example below.
    - The reply MUST start with '{{' and end with '}}' — no extra text.
    
    Example response:
    {{
      "workout_days": ["monday", "wednesday"],
      "exercises": [
        {{
          "day": "monday",
          "exercises": [
            {{
              "name": "Dumbbell Rows",
              "sets": "3",
              "reps": "12",
              "gif_link": null,  // put the 'None' here
              "weight": "20",    // kg
              "set_id": null,
              "drop_set": false
            }}
          ]
        }},
        {{
          "day": "wednesday",
          "exercises": [
            {{
              "name": "Lat Pulldown",
              "sets": "3",
              "reps": "10",
              "gif_link": null,
              "weight": "50",
              "set_id": null,
              "drop_set": false
            }}
          ]
        }}
      ]
    }}
"""

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
