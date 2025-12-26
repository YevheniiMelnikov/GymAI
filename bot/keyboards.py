from aiogram.types import InlineKeyboardButton as KbBtn
from aiogram.types import WebAppInfo

from bot.keyboard_builder import KeyboardBuilder, SafeInlineKeyboardMarkup as KbMarkup
from bot.texts import ButtonText, translate
from config.app_settings import settings
from bot.utils.diet_plans import (
    DIET_PRODUCT_CALLBACK_PREFIX,
    DIET_PRODUCT_OPTIONS,
    DIET_PRODUCTS_BACK,
    DIET_PRODUCTS_DONE,
    DIET_RESULT_MENU,
    DIET_RESULT_REPEAT,
)


def select_language_kb() -> KbMarkup:
    buttons = [
        [KbBtn(text="UA", callback_data="ua")],
        [KbBtn(text="ENG", callback_data="eng")],
        [KbBtn(text="RU", callback_data="ru")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def main_menu_kb(lang: str, *, webapp_url: str | None = None) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.my_profile, "my_profile")]]
    if webapp_url:
        buttons.append([builder.add(ButtonText.my_program, webapp_url=webapp_url)])
    else:
        buttons.append([builder.add(ButtonText.my_program, "my_workouts")])
    buttons.append([builder.add(ButtonText.ask_ai, "ask_ai", bot_name=settings.BOT_NAME)])
    buttons.append([builder.add(ButtonText.create_diet, "create_diet")])
    buttons.append([builder.add(ButtonText.feedback, "feedback")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def balance_menu_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.prev_menu, "back")]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def tariff_plans_kb(lang: str, plans: list[str]) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText[f"{plan}_plan"], f"plan_{plan}")] for plan in plans]
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def select_gender_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.male, "male")],
        [builder.add(ButtonText.female, "female")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def profile_menu_kb(lang: str, show_balance: bool = False) -> KbMarkup:
    builder = KeyboardBuilder(lang)
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


def edit_profile_kb(lang: str, *, show_diet: bool = False, show_language: bool = False) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.workout_experience, "workout_experience")],
        [builder.add(ButtonText.workout_goals, "workout_goals")],
        [builder.add(ButtonText.workout_location, "workout_location")],
        [builder.add(ButtonText.weight, "weight")],
        [builder.add(ButtonText.height, "height")],
        [builder.add(ButtonText.health_notes, "health_notes")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    if show_diet:
        buttons.insert(-1, [builder.add(ButtonText.diet_allergies, "diet_allergies")])
        buttons.insert(-1, [builder.add(ButtonText.diet_products, "diet_products")])
    if show_language:
        buttons.insert(-1, [builder.add(ButtonText.language, "language")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_experience_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.beginner, "0-1")],
        [builder.add(ButtonText.intermediate, "1-3")],
        [builder.add(ButtonText.advanced, "3-5")],
        [builder.add(ButtonText.experienced, "5+")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def ask_ai_prompt_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.prev_menu, "ask_ai_back")]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def diet_result_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.diet_again, DIET_RESULT_REPEAT), builder.add(ButtonText.main_menu, DIET_RESULT_MENU)]
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def ask_ai_again_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.ask_ai_again, "ask_ai_again")],
        [builder.add(ButtonText.main_menu, "ask_ai_main_menu")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def enter_wishes_kb(lang: str, webapp_url: str | None) -> KbMarkup | None:
    if not webapp_url:
        return None
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.prev_menu, webapp_url=webapp_url)]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def workout_days_selection_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [
            KbBtn(text="➖", callback_data="workout_days_minus"),
            KbBtn(text="➕", callback_data="workout_days_plus"),
        ],
        [builder.add(ButtonText.prev_menu, "workout_days_back"), builder.add(ButtonText.done, "workout_days_continue")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def choose_payment_options_kb(lang: str, option: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.select, f"select_{option}")],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def workout_location_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.gym_workout, "gym")],
        [builder.add(ButtonText.home_workout, "home")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def feedback_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.prev_menu, "back")]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def feedback_menu_kb(lang: str, *, faq_url: str | None = None) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.send_feedback, "send_feedback")],
    ]
    if faq_url:
        buttons.append([builder.add(ButtonText.faq, webapp_url=faq_url)])
    else:
        buttons.append([builder.add(ButtonText.faq, "faq_unavailable")])
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def program_view_kb(lang: str, webapp_url: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [KbBtn(text=translate(ButtonText.view, lang), web_app=WebAppInfo(url=webapp_url))],
        [builder.add(ButtonText.quit, "quit")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def subscription_type_kb(lang: str, services: list[tuple[str, int]]) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    labels = {
        "subscription_1_month": ButtonText.subscription_1_month,
        "subscription_6_months": ButtonText.subscription_6_months,
        "subscription_12_months": ButtonText.subscription_12_months,
    }
    buttons: list[list[KbBtn]] = []
    for service_name, price in services:
        label_key = labels.get(service_name)
        if label_key is None:
            continue
        label = translate(label_key, lang)
        text = f"{label} - {price} GYMCOIN"
        buttons.append([KbBtn(text=text, callback_data=f"subscription_type_{service_name}")])
    buttons.append([builder.add(ButtonText.prev_menu, "back")])
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def weekly_survey_kb(lang: str, webapp_url: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [[builder.add(ButtonText.weekly_survey_answer, webapp_url=webapp_url)]]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def yes_no_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.answer_no, "no"), builder.add(ButtonText.answer_yes, "yes")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=1)


def diet_confirm_kb(lang: str) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = [
        [builder.add(ButtonText.prev_menu, "back"), builder.add(ButtonText.confirm_generate, "confirm_generate")],
    ]
    return KbMarkup(inline_keyboard=buttons, row_width=2)


def payment_kb(lang: str, service_type: str, *, webapp_url: str | None = None, link: str | None = None) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    if webapp_url:
        pay_button = KbBtn(text=translate(ButtonText.pay, lang), web_app=WebAppInfo(url=webapp_url))
    elif link:
        pay_button = KbBtn(text=translate(ButtonText.pay, lang), url=link)
    else:
        raise ValueError("payment_kb requires either webapp_url or link")
    done_button = builder.add(ButtonText.done, "done")
    buttons = [
        [pay_button, done_button],
        [builder.add(ButtonText.prev_menu, "back")],
    ]
    return KbMarkup(inline_keyboard=buttons)


def diet_products_kb(lang: str, selected: set[str]) -> KbMarkup:
    builder = KeyboardBuilder(lang)
    buttons = []
    for option in DIET_PRODUCT_OPTIONS:
        buttons.append(
            [
                builder.create_toggle(
                    ButtonText[option],
                    f"{DIET_PRODUCT_CALLBACK_PREFIX}{option}",
                    option in selected,
                    " ✅",
                    "",
                )
            ]
        )
    buttons.append(
        [
            builder.add(ButtonText.prev_menu, DIET_PRODUCTS_BACK),
            builder.add(ButtonText.done, DIET_PRODUCTS_DONE),
        ]
    )
    return KbMarkup(inline_keyboard=buttons, row_width=1)
