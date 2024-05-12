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
    work_experience = State()
    additional_info = State()
    payment_details = State()
    profile_photo = State()

    edit_profile = State()
    action_choice = State()
    feedback = State()
    profile = State()
    new_coach_request = State
    choose_coach = State()
    coach_selection = State()

    password_reset = State()
    password_retype = State()
