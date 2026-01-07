from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    select_language = State()
    gender = State()
    born_in = State()
    workout_goals = State()
    workout_location = State()
    weight = State()
    height = State()
    workout_experience = State()
    health_notes_choice = State()
    health_notes = State()
    accept_policy = State()
    ask_ai_question = State()
