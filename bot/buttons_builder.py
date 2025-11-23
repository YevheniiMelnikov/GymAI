import html
import re
from types import SimpleNamespace
from typing import cast

from aiogram.types import InlineKeyboardButton, WebAppInfo

from bot.texts import ButtonText, btn_text


class ButtonsBuilder:
    def __init__(self, lang: str):
        self.lang = lang

    @staticmethod
    def _replace_emoji_tags(text: str) -> str:
        text = re.sub(r'<tg-emoji emoji-id="([^"]+)">([^<]+)</tg-emoji>', r"\2", text)
        return text

    @staticmethod
    def _resolve_key(text_key: ButtonText | str) -> ButtonText:
        return text_key if isinstance(text_key, ButtonText) else ButtonText[text_key]

    def add(
        self, text_key: ButtonText | str, callback: str | None = None, webapp_url: str | None = None, **format_args
    ) -> InlineKeyboardButton:
        key = self._resolve_key(text_key)
        text = btn_text(key, lang=self.lang).format(**format_args)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        try:
            if webapp_url:
                web_app = _create_web_app(webapp_url)
                return InlineKeyboardButton(text=formatted_text, web_app=web_app)
            return InlineKeyboardButton(text=formatted_text, callback_data=callback)
        except TypeError:
            return _create_fallback_button(formatted_text, callback, webapp_url)

    def create_toggle(
        self, text_key: ButtonText | str, callback: str, condition: bool, true_text: str, false_text: str
    ) -> InlineKeyboardButton:
        key = self._resolve_key(text_key)
        text = btn_text(key, lang=self.lang).format(true_text if condition else false_text)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        return InlineKeyboardButton(text=formatted_text, callback_data=callback)


def _create_web_app(url: str) -> WebAppInfo:
    try:
        return WebAppInfo(url=url)
    except TypeError:
        web_app = SimpleNamespace(url=url)
        return cast(WebAppInfo, web_app)


def _create_fallback_button(text: str, callback: str | None, webapp_url: str | None) -> InlineKeyboardButton:
    button = SimpleNamespace(text=text)
    if webapp_url:
        button.web_app = _create_web_app(webapp_url)
    else:
        button.callback_data = callback
    return cast(InlineKeyboardButton, button)
