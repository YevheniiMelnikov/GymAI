from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def language_choice() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Українська 🇺🇦")
    kb.button(text="English 🇬🇧")
    kb.button(text="Русский 🇷🇺")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def main_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # kb.button(
    #     text=translate(ButtonText.text_me, lang=lang_code),
    #     url=os.getenv("OWNER_LINK"),
    #     callback_data="text_me",
    # )
    # kb.button(
    #     text=translate(ButtonText.show_events, lang=lang_code),
    #     callback_data="show_events",
    # )
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)
