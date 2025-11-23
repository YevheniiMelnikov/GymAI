from typing import Any

from aiogram.types import InlineKeyboardButton as KbBtn
from aiogram.types import InlineKeyboardMarkup as _RawKbMarkup, WebAppInfo

from bot.buttons_builder import ButtonsBuilder
from bot.texts import ButtonText, btn_text
from core.schemas import Exercise


class SafeInlineKeyboardMarkup(_RawKbMarkup):  # type: ignore[misc]
    def __init__(
        self, *args: Any, inline_keyboard: list[list[KbBtn]] | None = None, row_width: int | None = None, **kwargs: Any
    ):
        inline_keyboard_value = inline_keyboard if inline_keyboard is not None else []
        build_kwargs: dict[str, Any] = {"inline_keyboard": inline_keyboard_value}
        if row_width is not None:
            build_kwargs["row_width"] = row_width
        try:
            super().__init__(*args, **build_kwargs, **kwargs)
        except TypeError:
            if inline_keyboard is not None:
                setattr(self, "inline_keyboard", inline_keyboard)
            elif hasattr(self, "inline_keyboard"):
                setattr(self, "inline_keyboard", inline_keyboard_value)
            if row_width is not None:
                setattr(self, "row_width", row_width)


KbMarkup = SafeInlineKeyboardMarkup


def select_language_kb() -> KbMarkup:
    buttons = [
        [KbBtn(text="UA", callback_data="ua")],
        [KbBtn(text="ENG", callback_data="eng")],
        [KbBtn(text="RU", callback_data="ru")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def main_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.my_profile, "my_profile")],
        [builder.add(ButtonText.my_program, "my_workouts")],
        [builder.add(ButtonText.feedback, "feedback")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def balance_menu_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.tariff_plans, "plans")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def tariff_plans_kb(lang: str, plans: list[str]) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(ButtonText[f"{plan}_plan"], f"plan_{plan}")] for plan in plans]
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def ai_services_kb(lang: str, services: list[str]) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(ButtonText[service], f"ai_service_{service}")] for service in services]
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_gender_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.male, "male")],
        [builder.add(ButtonText.female, "female")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def profile_menu_kb(lang: str, show_balance: bool = False) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons: list[list[KbBtn]] = []
    if show_balance:
        buttons.append([builder.add(ButtonText.balance_status, "balance")])
    buttons.extend(
        [
            [builder.add(ButtonText.edit, "profile_edit")],
            [builder.add(ButtonText.delete, "profile_delete")],
            [builder.add(ButtonText.prev_menu, "back")],
        ]
    )
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def edit_profile_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.workout_experience, "workout_experience")],
        [builder.add(ButtonText.workout_goals, "workout_goals")],
        [builder.add(ButtonText.health_notes, "health_notes")],
        [builder.add(ButtonText.weight, "weight")],
        [builder.add(ButtonText.photo, "photo")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_experience_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.beginner, "0-1")],
        [builder.add(ButtonText.intermediate, "1-3")],
        [builder.add(ButtonText.advanced, "3-5")],
        [builder.add(ButtonText.experienced, "5+")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_service_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.subscription, "subscription")],
        [builder.add(ButtonText.program, "program")],
        [builder.add(ButtonText.ask_ai, "ask_ai")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def ask_ai_prompt_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(ButtonText.prev_menu, "ask_ai_back")]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def ask_ai_again_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(ButtonText.ask_ai_again, "ask_ai_again")]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_action_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons: list[list[KbBtn]] = []
    if webapp_url:
        buttons.append([builder.add(ButtonText.view, webapp_url=webapp_url)])
    buttons.append([builder.add(ButtonText.new_workout_plan, "new_subscription")])
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def program_manage_kb(lang: str, workouts_per_week: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add(ButtonText.save, "save"),
            builder.add(ButtonText.reset_program, "reset"),
        ]
    ]
    if workouts_per_week > 1:
        buttons.append([builder.add(ButtonText.next_day, "add_next_day")])
    buttons.append([builder.add(ButtonText.set_mode, "toggle_set")])
    buttons.append([builder.add(ButtonText.quit, "quit")])
    return KbMarkup(inline_keyboard=buttons)


def choose_payment_options_kb(lang: str, option: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.select, f"select_{option}")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def client_msg_bk(lang: str, profile_id: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.answer, f"answer_{profile_id}")],
        [builder.add(ButtonText.later, "later")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def gift_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [[builder.add(ButtonText.get, "get")]]
    return KbMarkup(inline_keyboard=buttons)


def workout_type_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.gym_workout, "gym")],
        [builder.add(ButtonText.home_workout, "home")],
        [builder.add(ButtonText.prev_menu, "workouts_back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_days_kb(lang: str, selected_days: list) -> KbMarkup:
    buttons = []
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day_key in days_of_week:
        raw_text = btn_text(ButtonText[day_key], lang)
        text = f"✔️ {raw_text}" if day_key in selected_days else raw_text
        buttons.append([KbBtn(text=text, callback_data=day_key)])
    builder = ButtonsBuilder(lang)
    complete_button = [builder.add(ButtonText.save, "complete")]
    buttons.append(complete_button)
    return KbMarkup(inline_keyboard=buttons)


def program_view_kb(lang: str, webapp_url: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [KbBtn(text=btn_text(ButtonText.view, lang), web_app=WebAppInfo(url=webapp_url))],
        [builder.add(ButtonText.quit, "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_survey_kb(lang: str, day: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add(ButtonText.answer_yes, f"yes_{day}"),
            builder.add(ButtonText.answer_no, f"no_{day}"),
        ]
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def workout_results_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add(ButtonText.answer_yes, "completed"),
            builder.add(ButtonText.answer_no, "not_completed"),
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


def program_edit_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.back, "prev_day"), builder.add(ButtonText.forward, "next_day")],
        [builder.add(ButtonText.add_exercise, "exercise_add")],
        [builder.add(ButtonText.set_mode, "toggle_set")],
        [builder.add(ButtonText.edit_exercise, "exercise_edit")],
        [builder.add(ButtonText.delete_exercise, "exercise_delete")],
        [builder.add(ButtonText.toggle_drop_set, "toggle_drop_set")],
        [builder.add(ButtonText.save, "finish_editing"), builder.add(ButtonText.reset_program, "reset")],
        [builder.add(ButtonText.prev_menu, "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def show_subscriptions_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons: list[list[KbBtn]] = []
    if webapp_url:
        buttons.append([KbBtn(text=btn_text(ButtonText.view, lang), web_app=WebAppInfo(url=webapp_url))])

    buttons.extend(
        [
            [builder.add(ButtonText.history, "history")],
            [builder.add(ButtonText.edit_days, "change_days")],
            [builder.add(ButtonText.cancel_subscription, "cancel")],
            [builder.add(ButtonText.prev_menu, "back")],
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
        [builder.add(ButtonText.sets, "sets")],
        [builder.add(ButtonText.reps, "reps")],
        [builder.add(ButtonText.weight, "weight")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_manage_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.back, "prev_day"), builder.add(ButtonText.forward, "next_day")],
        [builder.add(ButtonText.edit, "edit")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_view_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.view, "subscription_view")],
        [builder.add(ButtonText.later, "later")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def yes_no_kb(lang: str) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.answer_yes, "yes"), builder.add(ButtonText.answer_no, "no")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def payment_kb(lang: str, service_type: str, *, webapp_url: str | None = None, link: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    if webapp_url:
        pay_button = KbBtn(text=btn_text(ButtonText.pay, lang), web_app=WebAppInfo(url=webapp_url))
    elif link:
        pay_button = KbBtn(text=btn_text(ButtonText.pay, lang), url=link)
    else:
        raise ValueError("payment_kb requires either webapp_url or link")
    done_button = builder.add(ButtonText.done, "done")
    buttons = [
        [pay_button, done_button],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def program_action_kb(lang: str, webapp_url: str | None = None) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [builder.add(ButtonText.view, webapp_url=webapp_url)],
        [builder.add(ButtonText.new_workout_plan, "new_program")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def history_nav_kb(lang: str, prefix: str, index: int) -> KbMarkup:
    builder = ButtonsBuilder(lang)
    buttons = [
        [
            builder.add(ButtonText.back, f"{prefix}_prev_{index - 1}"),
            builder.add(ButtonText.forward, f"{prefix}_next_{index + 1}"),
        ],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)
