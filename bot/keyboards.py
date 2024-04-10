from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from texts.text_manager import ButtonText, translate

codes = {"Українська 🇺🇦": "ua", "English 🇬🇧": "eng", "Русский 🇷🇺": "ru"}


def language_choice() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Українська 🇺🇦")
    kb.button(text="English 🇬🇧")
    kb.button(text="Русский 🇷🇺")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def choose_gender(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.male, lang=lang_code), callback_data="male")
    kb.button(text=translate(ButtonText.female, lang=lang_code), callback_data="female")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def choose_account_type(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.client, lang=lang_code), callback_data="client")
    kb.button(text=translate(ButtonText.coach, lang=lang_code), callback_data="coach")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def main_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)
