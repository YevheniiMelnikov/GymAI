from aiogram import Bot
from aiogram.types import Message


class BotMessageProxy:
    """Proxy for sending bot messages without a Telegram update object."""

    def __init__(self, *, bot: Bot, chat_id: int):
        self._bot = bot
        self._chat_id = chat_id

    @property
    def chat_id(self) -> int:
        return self._chat_id

    async def answer(self, text: str, *args, **kwargs) -> Message:
        return await self._bot.send_message(self._chat_id, text, *args, **kwargs)

    async def answer_photo(self, photo, *args, **kwargs) -> Message:  # type: ignore[override]
        return await self._bot.send_photo(self._chat_id, photo, *args, **kwargs)

    async def answer_document(self, document, *args, **kwargs) -> Message:  # type: ignore[override]
        return await self._bot.send_document(self._chat_id, document, *args, **kwargs)

    async def answer_video(self, video, *args, **kwargs) -> Message:  # type: ignore[override]
        return await self._bot.send_video(self._chat_id, video, *args, **kwargs)
