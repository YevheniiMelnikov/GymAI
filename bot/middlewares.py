from contextlib import suppress

from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from typing import Callable, Awaitable

from core.cache import Cache
from core.exceptions import ProfileNotFoundError


class ProfileMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[..., Awaitable], message: Message, state: FSMContext) -> Awaitable:
        user_id = getattr(message.from_user, "id", None)
        profile = None
        if user_id is not None:
            with suppress(ProfileNotFoundError):
                profile = await Cache.profile.get_profile(user_id)
        if isinstance(state, FSMContext):
            await state.update_data(profile=profile.model_dump() if profile else None)
        return await handler(message, state)
