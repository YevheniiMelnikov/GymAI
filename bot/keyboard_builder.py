import html
import re
from types import SimpleNamespace
from typing import Any, cast

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot.texts import ButtonText, translate


class SafeInlineKeyboardMarkup(InlineKeyboardMarkup):  # type: ignore[misc]
    """Guard InlineKeyboardMarkup init against signature mismatches."""

    def __init__(
        self,
        *args: Any,
        inline_keyboard: list[list[InlineKeyboardButton]] | None = None,
        row_width: int | None = None,
        **kwargs: Any,
    ) -> None:
        inline_keyboard_value = inline_keyboard if inline_keyboard is not None else []
        try:
            if row_width is None:
                super().__init__(*args, inline_keyboard=inline_keyboard_value, **kwargs)
            else:
                super().__init__(*args, inline_keyboard=inline_keyboard_value, row_width=row_width, **kwargs)
        except TypeError:
            if inline_keyboard is not None:
                setattr(self, "inline_keyboard", inline_keyboard)
            elif hasattr(self, "inline_keyboard"):
                setattr(self, "inline_keyboard", inline_keyboard_value)
            if row_width is not None:
                setattr(self, "row_width", row_width)


class KeyboardBuilder:
    """Build localized inline keyboards with safe fallbacks."""

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
        text = translate(key, lang=self.lang).format(**format_args)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        try:
            if webapp_url:
                web_app = self._create_web_app(webapp_url)
                return InlineKeyboardButton(text=formatted_text, web_app=web_app)
            return InlineKeyboardButton(text=formatted_text, callback_data=callback)
        except TypeError:
            return self._create_fallback_button(formatted_text, callback, webapp_url)

    def create_toggle(
        self, text_key: ButtonText | str, callback: str, condition: bool, true_text: str, false_text: str
    ) -> InlineKeyboardButton:
        key = self._resolve_key(text_key)
        text = translate(key, lang=self.lang)
        formatted_text = self._replace_emoji_tags(html.unescape(text))
        suffix = true_text if condition else false_text
        return InlineKeyboardButton(text=f"{formatted_text}{suffix}", callback_data=callback)

    @staticmethod
    def _create_web_app(url: str) -> WebAppInfo:
        try:
            return WebAppInfo(url=url)
        except TypeError:
            web_app = SimpleNamespace(url=url)
            return cast(WebAppInfo, web_app)

    @classmethod
    def _create_fallback_button(cls, text: str, callback: str | None, webapp_url: str | None) -> InlineKeyboardButton:
        button = SimpleNamespace(text=text)
        if webapp_url:
            button.web_app = cls._create_web_app(webapp_url)
        else:
            button.callback_data = callback
        return cast(InlineKeyboardButton, button)
