from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as Btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.texts.text_manager import btn_text


def select_language_kb() -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text="UA", callback_data="ua")],
        [Btn(text="ENG", callback_data="eng")],
        [Btn(text="RU", callback_data="ru")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def select_gender_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("male", lang), callback_data="male")
    kb.button(text=btn_text("female", lang), callback_data="female")
    return kb.as_markup(one_time_keyboard=True)


def select_role_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("client", lang), callback_data="client")
    kb.button(text=btn_text("coach", lang), callback_data="coach")
    return kb.as_markup(one_time_keyboard=True)


def client_menu_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("my_profile", lang), callback_data="my_profile")],
        [Btn(text=btn_text("my_program", lang), callback_data="my_workouts")],
        [Btn(text=btn_text("feedback", lang), callback_data="feedback")],
        [Btn(text=btn_text("logout", lang), callback_data="logout")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def coach_menu_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("my_profile", lang), callback_data="my_profile")],
        [Btn(text=btn_text("my_clients", lang), callback_data="my_clients")],
        [Btn(text=btn_text("feedback", lang), callback_data="feedback")],
        [Btn(text=btn_text("logout", lang), callback_data="logout")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def action_choice_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("sign_in", lang), callback_data="sign_in")
    kb.button(text=btn_text("sign_up", lang), callback_data="sign_up")
    return kb.as_markup(one_time_keyboard=True)


def profile_menu_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("edit", lang), callback_data="profile_edit"),
            Btn(text=btn_text("delete", lang), callback_data="profile_delete"),
        ],
        [
            Btn(text=btn_text("prev_menu", lang), callback_data="back"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def edit_client_profile_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("workout_experience", lang), callback_data="workout_experience")],
        [Btn(text=btn_text("workout_goals", lang), callback_data="workout_goals")],
        [Btn(text=btn_text("health_notes", lang), callback_data="health_notes")],
        [Btn(text=btn_text("weight", lang), callback_data="weight")],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def edit_coach_profile_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("work_experience", lang), callback_data="work_experience")],
        [Btn(text=btn_text("additional_info", lang), callback_data="additional_info")],
        [Btn(text=btn_text("payment_details", lang), callback_data="payment_details")],
        [Btn(text=btn_text("program_price", lang), callback_data="program_price")],
        [Btn(text=btn_text("subscription_price", lang), callback_data="subscription_price")],
        [Btn(text=btn_text("photo", lang), callback_data="photo")],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def workout_experience_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("beginner", lang), callback_data="0-1")],
        [Btn(text=btn_text("intermediate", lang), callback_data="1-3")],
        [Btn(text=btn_text("advanced", lang), callback_data="3-5")],
        [Btn(text=btn_text("experienced", lang), callback_data="5+")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def new_coach_kb(profile_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👍", callback_data=f"approve_{profile_id}")
    kb.button(text="👎", callback_data=f"decline_{profile_id}")
    return kb.as_markup(one_time_keyboard=True)


def choose_coach_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("choose_coach", lang), callback_data="choose_coach")],
        [
            Btn(text=btn_text("prev_menu", lang), callback_data="back"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def coach_select_kb(lang: str, coach_id: int, current_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("select", lang), callback_data=f"selected_{coach_id}")],
        [
            Btn(text=btn_text("back", lang), callback_data=f"prev_{current_index - 1}"),
            Btn(text=btn_text("forward", lang), callback_data=f"next_{current_index + 1}"),
        ],
        [Btn(text=btn_text("prev_menu", lang), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def client_select_kb(lang: str, client_id: int, current_index: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("back", lang), callback_data=f"prev_{current_index - 1}"),
            Btn(text=btn_text("forward", lang), callback_data=f"next_{current_index + 1}"),
        ],
        [Btn(text=btn_text("program", lang), callback_data=f"program_{client_id}")],
        [Btn(text=btn_text("subscription", lang), callback_data=f"subscription_{client_id}")],
        [
            Btn(text=btn_text("contact_client", lang), callback_data=f"contact_{client_id}"),
        ],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def new_message_kb(lang: str, profile_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("answer", lang), callback_data=f"answer_{profile_id}")
    kb.button(text=btn_text("quit", lang), callback_data="quit")
    return kb.as_markup(one_time_keyboard=True)


def select_service_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("subscription", lang), callback_data="subscription")],
        [Btn(text=btn_text("program", lang), callback_data="program")],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def program_manage_kb(lang: str, workouts_per_week: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("save", lang), callback_data="save"),
            Btn(text=btn_text("reset_program", lang), callback_data="reset"),
        ]
    ]

    if workouts_per_week > 1:
        buttons.append([Btn(text=btn_text("next_day", lang), callback_data="add_next_day")])

    buttons.append([Btn(text=btn_text("quit", lang), callback_data="quit")])
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def choose_payment_options_kb(lang: str, option: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("select", lang), callback_data=f"select_{option}"),
        ],
        [
            Btn(text=btn_text("prev_menu", lang), callback_data="back"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def client_msg_bk(lang: str, client_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("answer", lang), callback_data=f"answer_{client_id}")
    kb.button(text=btn_text("later", lang), callback_data="later")
    return kb.as_markup(one_time_keyboard=True)


def incoming_request_kb(lang: str, service: str, client_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("create", lang), callback_data=f"create_{service}_{client_id}")
    kb.button(text=btn_text("later", lang), callback_data="later")
    return kb.as_markup(one_time_keyboard=True)


def gift_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("get", lang), callback_data="get")
    return kb.as_markup(one_time_keyboard=True)


def workout_type_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("gym_workout", lang), callback_data="gym")],
        [Btn(text=btn_text("home_workout", lang), callback_data="home")],
        [Btn(text=btn_text("street_workout", lang), callback_data="street")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def select_days_kb(lang: str, selected_days: list) -> InlineKeyboardMarkup:
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    buttons = []

    for day in days_of_week:
        text = f"✔️ {btn_text(day, lang)}" if day in selected_days else btn_text(day, lang)
        buttons.append([Btn(text=text, callback_data=day)])

    complete_button = [Btn(text=btn_text("save", lang), callback_data="complete")]
    buttons.append(complete_button)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def program_view_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("back", lang), callback_data="previous"),
            Btn(text=btn_text("forward", lang), callback_data="next"),
        ],
        [Btn(text=btn_text("quit", lang), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def workout_survey_kb(lang: str, day: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("answer_yes", lang), callback_data=f"yes_{day}"),
            Btn(text=btn_text("answer_no", lang), callback_data=f"no_{day}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=2)


def workout_results_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("answer_yes", lang), callback_data="completed"),
            Btn(text=btn_text("answer_no", lang), callback_data="not_completed"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def sets_number_kb() -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text="1", callback_data="1"), Btn(text="2", callback_data="2")],
        [Btn(text="3", callback_data="3"), Btn(text="4", callback_data="4")],
        [Btn(text="5", callback_data="5")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=2)


def reps_number_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text="1-3", callback_data="1-3"),
            Btn(text="3-5", callback_data="3-5"),
            Btn(text="5-8", callback_data="5-8"),
            Btn(text="8-10", callback_data="8-10"),
        ],
        [
            Btn(text="12-15", callback_data="12-15"),
            Btn(text="15-20", callback_data="15-20"),
            Btn(text="20-30", callback_data="20-30"),
            Btn(text="30+", callback_data="30+"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=2)


def workout_feedback_kb(lang: str, client_id: int, day: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("contact_client", lang), callback_data=f"answer_{client_id}"),
            Btn(text=btn_text("edit", lang), callback_data=f"edit_{client_id}_{day}"),
        ],
        [Btn(text=btn_text("quit", lang), callback_data="quit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True)


def program_edit_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("back", lang), callback_data="prev_day"),
            Btn(text=btn_text("forward", lang), callback_data="next_day"),
        ],
        [Btn(text=btn_text("add_exercise", lang), callback_data="exercise_add")],
        [Btn(text=btn_text("edit_exercise", lang), callback_data="exercise_edit")],
        [Btn(text=btn_text("delete_exercise", lang), callback_data="exercise_delete")],
        [
            Btn(text=btn_text("save", lang), callback_data="finish_editing"),
            Btn(text=btn_text("reset_program", lang), callback_data="reset"),
        ],
        [Btn(text=btn_text("prev_menu", lang), callback_data="quit")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def show_subscriptions_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("exercises", lang), callback_data="exercises")],
        [Btn(text=btn_text("contact_coach", lang), callback_data="contact")],
        [Btn(text=btn_text("edit_days", lang), callback_data="change_days")],
        [Btn(text=btn_text("cancel_subscription", lang), callback_data="cancel")],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def select_exercise_kb(exercises: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for index, exercise in enumerate(exercises):
        buttons.append([Btn(text=exercise.get("name"), callback_data=str(index))])
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def edit_exercise_data_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("sets", lang), callback_data="sets")],
        [Btn(text=btn_text("reps", lang), callback_data="reps")],
        [Btn(text=btn_text("weight", lang), callback_data="weight")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def subscription_manage_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("back", lang), callback_data="prev_day"),
            Btn(text=btn_text("forward", lang), callback_data="next_day"),
        ],
        [Btn(text=btn_text("edit", lang), callback_data="edit")],
        [Btn(text=btn_text("prev_menu", lang), callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def subscription_view_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [Btn(text=btn_text("view", lang), callback_data="subscription_view")],
        [Btn(text=btn_text("later", lang), callback_data="later")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def yes_no_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("answer_yes", lang), callback_data="yes"),
            Btn(text=btn_text("answer_no", lang), callback_data="no"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)


def payment_kb(lang: str, link: str, request_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                Btn(text=btn_text("pay", lang), callback_data=request_type, url=link),
                Btn(text=btn_text("done", lang), callback_data="done"),
            ],
            [
                Btn(text=btn_text("prev_menu", lang), callback_data="back"),
            ],
        ]
    )


def program_action_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            Btn(text=btn_text("view", lang), callback_data="show_old"),
            Btn(text=btn_text("new_program", lang), callback_data="new_program"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons, one_time_keyboard=True, row_width=1)
