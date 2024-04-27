from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from texts.text_manager import ButtonText, translate

codes = {"Українська": "ua", "English": "eng", "Русский": "ru"}  # TODO: FIND BETTER SOLUTION


def language_choice() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Українська")
    kb.button(text="English")
    kb.button(text="Русский")
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


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


def action_choice(lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.sign_in, lang=lang_code), callback_data="sign_in")
    kb.button(text=translate(ButtonText.sign_up, lang=lang_code), callback_data="sign_up")
    return kb.as_markup(one_time_keyboard=True)
