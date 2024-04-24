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

    client_menu = State()
    coach_menu = State()
    action_choice = State()

    password_reset = State()
    password_retype = State()
