from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    main_menu = State()
    language_choice = State()
    email = State()
    action_choice = State()
    password_retype = State()
    username = State()
    password = State()
    gender = State()
    account_type = State()
    birth_date = State()
    client_menu = State()
    coach_menu = State()
