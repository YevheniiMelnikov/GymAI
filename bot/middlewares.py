from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, MenuButtonDefault, Message
from loguru import logger

from core.cache import Cache
from core.exceptions import ProfileNotFoundError


class ProfileMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        state: FSMContext | None = data.get("state")
        tg_user = getattr(event, "from_user", None)

        if isinstance(event, (Message, CallbackQuery)):
            bot = getattr(event, "bot", None)
            if bot is not None:
                await _ensure_default_menu_button(bot)

        if tg_user and state:
            try:
                profile = await Cache.profile.get_profile(tg_user.id)
            except ProfileNotFoundError:
                profile = None
            except Exception as e:
                logger.error(f"Error fetching profile for user {tg_user.id}: {e}")
                profile = None

            await state.update_data(profile=profile.model_dump(mode="json") if profile else None)

        return await handler(event, data)


async def _ensure_default_menu_button(bot: Bot) -> None:
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_chat_menu_button failed: {}", exc)
