import html
import re

from aiogram.types import InlineKeyboardButton

from bot.texts.text_manager import btn_text


class ButtonsBuilder:
    def __init__(self, lang: str):
        self.lang = lang

    @staticmethod
    def _replace_emoji_tags(text: str) -> str:
        text = re.sub(r'<tg-emoji emoji-id="([^"]+)">([^<]+)</tg-emoji>', r"\2", text)
        return text

    def add(self, text_key: str, callback: str, **format_args) -> InlineKeyboardButton:
        text = btn_text(text_key, lang=self.lang).format(**format_args)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        return InlineKeyboardButton(text=formatted_text, callback_data=callback)

    def create_toggle(
        self, text_key: str, callback: str, condition: bool, true_text: str, false_text: str
    ) -> InlineKeyboardButton:
        text = btn_text(text_key, lang=self.lang).format(true_text if condition else false_text)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        return InlineKeyboardButton(text=formatted_text, callback_data=callback)
