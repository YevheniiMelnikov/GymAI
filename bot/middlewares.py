from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from loguru import logger

from core.cache import Cache
from core.exceptions import ProfileNotFoundError


class ProfileMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        state: FSMContext | None = data.get("state")
        tg_user = getattr(event, "from_user", None)

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
