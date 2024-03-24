from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    main_menu = State()
    language_choice = State()
