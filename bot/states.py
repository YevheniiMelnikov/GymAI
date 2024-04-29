from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    main_menu = State()
    language_choice = State()
    username = State()
    password = State()
    email = State()

    account_type = State()
    gender = State()
    birth_date = State()
    name = State()
    workout_goals = State()
    weight = State()
    workout_experience = State()
    health_notes = State()

    action_choice = State()
    feedback = State()
    profile = State()

    password_reset = State()
    password_retype = State()
