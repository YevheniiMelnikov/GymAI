from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from typing import Callable, Awaitable
from loguru import logger

from core.cache import Cache
from core.exceptions import ProfileNotFoundError


class ProfileMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[..., Awaitable], message: Message, state: FSMContext) -> Awaitable:
        user_id = getattr(message.from_user, "id", None)
        profile = None
        if user_id is not None:
            try:
                profile = await Cache.profile.get_profile(user_id)
            except ProfileNotFoundError:
                pass
            except Exception as e:
                logger.error(f"Error fetching profile for user {user_id}: {e}")
        if isinstance(state, FSMContext):
            await state.update_data(profile=profile.model_dump() if profile else None)
        return await handler(message, state)
