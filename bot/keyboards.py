from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from texts.text_manager import ButtonText, translate

codes = {"Українська 🇺🇦": "ua", "English 🇬🇧": "eng", "Русский 🇷🇺": "ru"} # TODO: FIND BETTER SOLUTION


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


def client_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.my_current_program, lang=lang_code), callback_data="my_program")
    kb.button(text=translate(ButtonText.give_feedback, lang=lang_code), callback_data="feedback")
    kb.button(text=translate(ButtonText.show_my_profile, lang=lang_code), callback_data="my_profile")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def coach_menu_keyboard(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.show_my_clients, lang=lang_code), callback_data="my_program")
    kb.button(text=translate(ButtonText.give_feedback, lang=lang_code), callback_data="feedback")
    kb.button(text=translate(ButtonText.show_my_profile, lang=lang_code), callback_data="my_profile")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)
