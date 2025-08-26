from aiogram.types import InlineKeyboardButton as KbBtn
from aiogram.types import InlineKeyboardMarkup as KbMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.buttons_builder import ButtonsBuilder
from bot.texts.text_manager import btn_text
from core.schemas import Exercise


def select_language_kb() -> KbMarkup:
    buttons = [
        [KbBtn(text="UA", callback_data="ua")],
        [KbBtn(text="ENG", callback_data="eng")],
        [KbBtn(text="RU", callback_data="ru")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def client_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("my_profile", "my_profile")],
        [builder.add("my_program", "my_workouts")],
        [builder.add("services", "services")],
        [builder.add("feedback", "feedback")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def balance_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("tariff_plans", "plans")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def tariff_plans_kb(lang: str, plans: list[str]) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(f"{plan}_plan", f"plan_{plan}")] for plan in plans]
    buttons.append([builder.add("prev_menu", "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def ai_services_kb(lang: str, services: list[str]) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(service, f"ai_service_{service}")] for service in services]
    buttons.append([builder.add("prev_menu", "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def coach_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("my_profile", "my_profile")],
        [builder.add("my_clients", "my_clients")],
        [builder.add("feedback", "feedback")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_gender_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("male", "male")],
        [builder.add("female", "female")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def select_role_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("client", "client")],
        [builder.add("coach", "coach")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def profile_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("edit", "profile_edit"),
            builder.add("delete", "profile_delete"),
        ],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def edit_client_profile_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("workout_experience", "workout_experience")],
        [builder.add("workout_goals", "workout_goals")],
        [builder.add("health_notes", "health_notes")],
        [builder.add("weight", "weight")],
        [builder.add("photo", "photo")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def edit_coach_profile_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("work_experience", "work_experience")],
        [builder.add("additional_info", "additional_info")],
        [builder.add("payment_details", "payment_details")],
        [builder.add("program_price", "program_price")],
        [builder.add("subscription_price", "subscription_price")],
        [builder.add("photo", "photo")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_experience_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("beginner", "0-1")],
        [builder.add("intermediate", "1-3")],
        [builder.add("advanced", "3-5")],
        [builder.add("experienced", "5+")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def new_coach_kb(profile_id: int) -> KbMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👍", callback_data=f"approve_{profile_id}")
    kb.button(text="👎", callback_data=f"decline_{profile_id}")
    return kb.as_markup(one_time_keyboard=True)


def choose_coach_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("ai_coach", "ai_coach")],
        [builder.add("choose_coach", "choose_coach")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def coach_select_kb(lang: str, coach_id: int, current_index: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("select", f"selected_{coach_id}")],
        [
            builder.add("back", f"prev_{current_index - 1}"),
            builder.add("forward", f"next_{current_index + 1}"),
        ],
        [builder.add("prev_menu", "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def client_select_kb(lang: str, profile_id: int, current_index: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("back", f"prev_{current_index - 1}"),
            builder.add("forward", f"next_{current_index + 1}"),
        ],
        [builder.add("program", f"program_{profile_id}")],
        [builder.add("subscription", f"subscription_{profile_id}")],
        [builder.add("contact_client", f"contact_{profile_id}")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def new_message_kb(lang: str, profile_id: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("answer", f"answer_{profile_id}")],
        [builder.add("quit", "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def select_service_kb(lang: str, has_coach: bool = False) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("subscription", "subscription")],
        [builder.add("program", "program")],
    ]
    if has_coach:
        buttons.append([builder.add("contact_coach", "contact")])
    buttons.append([builder.add("prev_menu", "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def services_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("ai_coach", "ai_coach")],
        [builder.add("choose_coach", "choose_coach")],
        [builder.add("balance_status", "balance")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def program_manage_kb(lang: str, workouts_per_week: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("save", "save"),
            builder.add("reset_program", "reset"),
        ]
    ]
    if workouts_per_week > 1:
        buttons.append([builder.add("next_day", "add_next_day")])
    buttons.append([builder.add("set_mode", "toggle_set")])
    buttons.append([builder.add("quit", "quit")])
    return KbMarkup(inline_keyboard=buttons)


def choose_payment_options_kb(lang: str, option: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("select", f"select_{option}")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def client_msg_bk(lang: str, profile_id: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("answer", f"answer_{profile_id}")],
        [builder.add("later", "later")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def incoming_request_kb(lang: str, service: str, profile_id: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("create", f"create_{service}_{profile_id}")],
        [builder.add("later", "later")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def gift_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add("get", "get")]]
    return KbMarkup(inline_keyboard=buttons)


def workout_type_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("gym_workout", "gym")],
        [builder.add("home_workout", "home")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_days_kb(lang: str, selected_days: list) -> KbMarkup:
    buttons = []
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days_of_week:
        raw_text = btn_text(day, lang)
        text = f"✔️ {raw_text}" if day in selected_days else raw_text
        buttons.append([KbBtn(text=text, callback_data=day)])
    builder = ButtonsBuilder(lang)
    complete_button = [builder.add("save", "complete")]
    buttons.append(complete_button)
    return KbMarkup(inline_keyboard=buttons)


def program_view_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)

    buttons = [
        [builder.add("back", "previous"), builder.add("forward", "next")],
        [builder.add("history", "history")],
    ]

    if webapp_url:
        buttons.append([KbBtn(text=btn_text("view", lang), web_app=WebAppInfo(url=webapp_url))])

    buttons.append([builder.add("quit", "quit")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_survey_kb(lang: str, day: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("answer_yes", f"yes_{day}"),
            builder.add("answer_no", f"no_{day}"),
        ]
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def workout_results_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("answer_yes", "completed"),
            builder.add("answer_no", "not_completed"),
        ]
    ]
    return KbMarkup(inline_keyboard=buttons)


def sets_number_kb() -> KbMarkup:
    buttons = [
        [KbBtn(text="1", callback_data="1"), KbBtn(text="2", callback_data="2")],
        [KbBtn(text="3", callback_data="3"), KbBtn(text="4", callback_data="4")],
        [KbBtn(text="5", callback_data="5")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def reps_number_kb() -> KbMarkup:
    buttons = [
        [
            KbBtn(text="1-3", callback_data="1-3"),
            KbBtn(text="3-5", callback_data="3-5"),
            KbBtn(text="5-8", callback_data="5-8"),
            KbBtn(text="8-10", callback_data="8-10"),
        ],
        [
            KbBtn(text="12-15", callback_data="12-15"),
            KbBtn(text="15-20", callback_data="15-20"),
            KbBtn(text="20-30", callback_data="20-30"),
            KbBtn(text="30+", callback_data="30+"),
        ],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def workout_feedback_kb(lang: str, profile_id: int, day: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("contact_client", f"answer_{profile_id}"),
            builder.add("edit", f"edit_{profile_id}_{day}"),
        ],
        [
            builder.add("quit", "quit"),
        ],
    ]
    return KbMarkup(inline_keyboard=buttons)


def program_edit_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("back", "prev_day"), builder.add("forward", "next_day")],
        [builder.add("add_exercise", "exercise_add")],
        [builder.add("set_mode", "toggle_set")],
        [builder.add("edit_exercise", "exercise_edit")],
        [builder.add("delete_exercise", "exercise_delete")],
        [builder.add("toggle_drop_set", "toggle_drop_set")],
        [builder.add("save", "finish_editing"), builder.add("reset_program", "reset")],
        [builder.add("prev_menu", "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def show_subscriptions_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons: list[list[KbBtn]] = []
    if webapp_url:
        buttons.append([KbBtn(text=btn_text("view", lang), web_app=WebAppInfo(url=webapp_url))])

    buttons.extend(
        [
            [builder.add("history", "history")],
            [builder.add("contact_coach", "contact")],
            [builder.add("edit_days", "change_days")],
            [builder.add("cancel_subscription", "cancel")],
            [builder.add("prev_menu", "back")],
        ]
    )
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_exercise_kb(exercises: list[Exercise]) -> KbMarkup:
    buttons = []
    for index, exercise in enumerate(exercises):
        buttons.append([KbBtn(text=exercise.name, callback_data=str(index))])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def edit_exercise_data_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("sets", "sets")],
        [builder.add("reps", "reps")],
        [builder.add("weight", "weight")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_manage_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("back", "prev_day"), builder.add("forward", "next_day")],
        [builder.add("edit", "edit")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_view_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("view", "subscription_view")],
        [builder.add("later", "later")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def yes_no_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("answer_yes", "yes"), builder.add("answer_no", "no")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def payment_kb(lang: str, link: str, service_type: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    pay_button = KbBtn(text=btn_text("pay", lang), callback_data=service_type, url=link)
    done_button = builder.add("done", "done")
    buttons = [
        [pay_button, done_button],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def program_action_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add("view", webapp_url=webapp_url), builder.add("new_program", "new_program")],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def history_nav_kb(lang: str, prefix: str, index: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add("back", f"{prefix}_prev_{index - 1}"),
            builder.add("forward", f"{prefix}_next_{index + 1}"),
        ],
        [builder.add("prev_menu", "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)
