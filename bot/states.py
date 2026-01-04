from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    main_menu = State()

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
    enter_wishes = State()
    accept_policy = State()

    diet_allergies_choice = State()
    diet_allergies = State()
    diet_products = State()
    diet_confirm_service = State()

    profile_delete = State()

    handle_payment = State()
    choose_plan = State()
    ask_ai_question = State()
    choose_subscription = State()
    split_number_selection = State()
    confirm_service = State()
