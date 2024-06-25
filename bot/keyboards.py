from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from texts.text_manager import ButtonText, translate


def language_choice() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Українська", callback_data="ua")],
        [InlineKeyboardButton(text="Русский", callback_data="ru")],
        [InlineKeyboardButton(text="English", callback_data="eng")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def choose_gender(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.male, lang=lang_code), callback_data="male")
    kb.button(text=translate(ButtonText.female, lang=lang_code), callback_data="female")
    return kb.as_markup(one_time_keyboard=True)


def choose_account_type(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.client, lang=lang_code), callback_data="client")
    kb.button(text=translate(ButtonText.coach, lang=lang_code), callback_data="coach")
    return kb.as_markup(one_time_keyboard=True)


def client_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.my_program, lang=lang_code), callback_data="my_program")],
        [InlineKeyboardButton(text=translate(ButtonText.feedback, lang=lang_code), callback_data="feedback")],
        [InlineKeyboardButton(text=translate(ButtonText.my_profile, lang=lang_code), callback_data="my_profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def coach_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.my_clients, lang=lang_code), callback_data="my_clients")],
        [InlineKeyboardButton(text=translate(ButtonText.feedback, lang=lang_code), callback_data="feedback")],
        [InlineKeyboardButton(text=translate(ButtonText.my_profile, lang=lang_code), callback_data="my_profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def action_choice_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.sign_in, lang=lang_code), callback_data="sign_in")
    kb.button(text=translate(ButtonText.sign_up, lang=lang_code), callback_data="sign_up")
    return kb.as_markup(one_time_keyboard=True)


def profile_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.back, lang=lang_code), callback_data="back")
    kb.button(text=translate(ButtonText.edit, lang=lang_code), callback_data="edit_profile")
    return kb.as_markup(one_time_keyboard=True)


def edit_client_profile(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=translate(ButtonText.workout_experience, lang=lang_code), callback_data="workout_experience"
            )
        ],
        [InlineKeyboardButton(text=translate(ButtonText.workout_goals, lang=lang_code), callback_data="workout_goals")],
        [InlineKeyboardButton(text=translate(ButtonText.health_notes, lang=lang_code), callback_data="health_notes")],
        [InlineKeyboardButton(text=translate(ButtonText.weight, lang=lang_code), callback_data="weight")],
        [InlineKeyboardButton(text=translate(ButtonText.back, lang=lang_code), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def edit_coach_profile(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=translate(ButtonText.work_experience, lang=lang_code), callback_data="work_experience"
            )
        ],
        [
            InlineKeyboardButton(
                text=translate(ButtonText.additional_info, lang=lang_code), callback_data="additional_info"
            )
        ],
        [
            InlineKeyboardButton(
                text=translate(ButtonText.payment_details, lang=lang_code), callback_data="payment_details"
            )
        ],
        [InlineKeyboardButton(text=translate(ButtonText.photo, lang=lang_code), callback_data="photo")],
        [InlineKeyboardButton(text=translate(ButtonText.back, lang=lang_code), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def workout_experience_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.beginner, lang=lang_code), callback_data="0-1")
    kb.button(text=translate(ButtonText.intermediate, lang=lang_code), callback_data="1-3")
    kb.button(text=translate(ButtonText.advanced, lang=lang_code), callback_data="3-5")
    kb.button(text=translate(ButtonText.experienced, lang=lang_code), callback_data="5+")
    return kb.as_markup(one_time_keyboard=True)


def new_coach_request() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Принять", callback_data="coach_approve")
    kb.button(text="Отклонить", callback_data="coach_decline")
    return kb.as_markup(one_time_keyboard=True)


def choose_coach(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.back, lang=lang_code), callback_data="back")
    kb.button(text=translate(ButtonText.choose_coach, lang=lang_code), callback_data="choose_coach")
    return kb.as_markup(one_time_keyboard=True)


def coach_select_menu(lang_code: str, coach_id: int, current_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.select, lang_code), callback_data=f"selected_{coach_id}")],
        [
            InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data=f"prev_{current_index - 1}"),
            InlineKeyboardButton(
                text=translate(ButtonText.forward, lang_code), callback_data=f"next_{current_index + 1}"
            ),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def client_select_menu(lang_code: str, client_id: int, current_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.program, lang_code), callback_data=f"program_{client_id}")],
        [
            InlineKeyboardButton(
                text=translate(ButtonText.subscription, lang_code), callback_data=f"subscription_{client_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=translate(ButtonText.contact_client, lang_code), callback_data=f"contact_{client_id}"
            ),
        ],
        [
            InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data=f"prev_{current_index - 1}"),
            InlineKeyboardButton(
                text=translate(ButtonText.forward, lang_code), callback_data=f"next_{current_index + 1}"
            ),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def incoming_message(lang_code: str, profile_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.answer, lang_code), callback_data=f"answer_{profile_id}")
    kb.button(text=translate(ButtonText.quit, lang_code), callback_data="quit")
    return kb.as_markup(one_time_keyboard=True)


def select_service(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.subscription, lang_code), callback_data="subscription")],
        [InlineKeyboardButton(text=translate(ButtonText.program, lang_code), callback_data="program")],
        [InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def program_manage_menu(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=translate(ButtonText.save, lang_code), callback_data="save"),
            InlineKeyboardButton(text=translate(ButtonText.reset_program, lang_code), callback_data="reset"),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.next_day, lang_code), callback_data="next")],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def choose_payment_options(lang_code: str, option: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.back, lang_code), callback_data="back")
    kb.button(text=translate(ButtonText.select, lang_code), callback_data=f"select_{option}")
    return kb.as_markup(one_time_keyboard=True)


def incoming_request(lang_code: str, client_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.answer, lang_code), callback_data=f"answer_{client_id}")
    kb.button(text=translate(ButtonText.later, lang_code), callback_data="later")
    return kb.as_markup(one_time_keyboard=True)


def gift(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.get, lang_code), callback_data="get")
    return kb.as_markup(one_time_keyboard=True)


def workout_type(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.gym_workout, lang_code), callback_data="gym")],
        [InlineKeyboardButton(text=translate(ButtonText.home_workout, lang_code), callback_data="home")],
        [InlineKeyboardButton(text=translate(ButtonText.street_workout, lang_code), callback_data="street")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def select_days(lang_code: str, selected_days: list) -> InlineKeyboardMarkup:
    days_of_week = {
        "monday": ButtonText.monday,
        "tuesday": ButtonText.tuesday,
        "wednesday": ButtonText.wednesday,
        "thursday": ButtonText.thursday,
        "friday": ButtonText.friday,
        "saturday": ButtonText.saturday,
        "sunday": ButtonText.sunday,
    }
    buttons = []

    for day, button_text in days_of_week.items():
        text = f"✔️ {translate(button_text, lang_code)}" if day in selected_days else translate(button_text, lang_code)
        buttons.append([InlineKeyboardButton(text=text, callback_data=day)])

    complete_button = [InlineKeyboardButton(text=translate(ButtonText.save, lang_code), callback_data="complete")]
    buttons.append(complete_button)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def program_view_kb(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data=f"prev_day"),
            InlineKeyboardButton(text=translate(ButtonText.forward, lang_code), callback_data="next_day"),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def workout_survey_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.answer_yes, lang_code), callback_data="yes")],
        [InlineKeyboardButton(text=translate(ButtonText.answer_no, lang_code), callback_data="no")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def workout_results(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.answer_yes, lang_code), callback_data="answer_yes")],
        [InlineKeyboardButton(text=translate(ButtonText.answer_no, lang_code), callback_data="answer_no")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def sets_number() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="1", callback_data="1"), InlineKeyboardButton(text="2", callback_data="2")],
        [InlineKeyboardButton(text="3", callback_data="3"), InlineKeyboardButton(text="4", callback_data="4")],
        [InlineKeyboardButton(text="5", callback_data="5")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=2)


def reps_number() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="1-3", callback_data="1-3"),
            InlineKeyboardButton(text="3-5", callback_data="3-5"),
            InlineKeyboardButton(text="5-8", callback_data="5-8"),
            InlineKeyboardButton(text="8-10", callback_data="8-10"),
        ],
        [
            InlineKeyboardButton(text="12-15", callback_data="12-15"),
            InlineKeyboardButton(text="15-20", callback_data="15-20"),
            InlineKeyboardButton(text="20-30", callback_data="20-30"),
            InlineKeyboardButton(text="30+", callback_data="30+"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=2)


def workout_feedback(lang_code: str, client_id: int, day: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=translate(ButtonText.contact_client, lang_code), callback_data=f"answer_{client_id}"
            ),
            InlineKeyboardButton(text=translate(ButtonText.edit, lang_code), callback_data=f"edit_{client_id}_{day}"),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def program_edit_kb(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data="prev_day"),
            InlineKeyboardButton(text=translate(ButtonText.forward, lang_code), callback_data="next_day"),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.add_exercise, lang_code), callback_data="exercise_add")],
        [InlineKeyboardButton(text=translate(ButtonText.edit_exercise, lang_code), callback_data="exercise_edit")],
        [InlineKeyboardButton(text=translate(ButtonText.delete_exercise, lang_code), callback_data="exercise_delete")],
        [InlineKeyboardButton(text=translate(ButtonText.save, lang_code), callback_data="finish_editing")],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def show_subscriptions_kb(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.exercises, lang_code), callback_data="exercises")],
        [InlineKeyboardButton(text=translate(ButtonText.contact_coach, lang_code), callback_data="contact")],
        [InlineKeyboardButton(text=translate(ButtonText.edit, lang_code), callback_data="edit")],
        [InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def select_exercise(exercises: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for index, exercise in enumerate(exercises):
        buttons.append([InlineKeyboardButton(text=exercise.get("name"), callback_data=str(index))])
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def edit_exercise_data(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.sets, lang_code), callback_data="sets")],
        [InlineKeyboardButton(text=translate(ButtonText.reps, lang_code), callback_data="reps")],
        [InlineKeyboardButton(text=translate(ButtonText.weight, lang_code), callback_data="weight")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def subscription_manage_menu(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=translate(ButtonText.back, lang_code), callback_data="prev_day"),
            InlineKeyboardButton(text=translate(ButtonText.forward, lang_code), callback_data="next_day"),
        ],
        [InlineKeyboardButton(text=translate(ButtonText.edit, lang_code), callback_data="edit")],
        [InlineKeyboardButton(text=translate(ButtonText.quit, lang_code), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def subscription_view_kb(lang_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=translate(ButtonText.view, lang_code), callback_data="view")],
        [InlineKeyboardButton(text=translate(ButtonText.later, lang_code), callback_data="later")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)
