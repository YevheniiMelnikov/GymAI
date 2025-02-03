from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from typing import Callable, Awaitable

from functions.profiles import get_or_load_profile


class ProfileMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[..., Awaitable], message: Message, state: FSMContext) -> Awaitable:
        profile = await get_or_load_profile(message.from_user.id)
        if profile:
            if isinstance(state, FSMContext):
                await state.update_data(profile=profile)
        else:
            if isinstance(state, FSMContext):
                await state.update_data(profile=None)
        return await handler(message, state)
