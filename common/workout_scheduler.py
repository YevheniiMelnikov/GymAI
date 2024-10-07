import os
from datetime import datetime, timedelta

import loguru
from aiogram import Bot, F, Router
from aiogram.client.session import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.keyboards import workout_results, workout_survey_keyboard
from bot.states import States
from common.cache_manager import cache_manager
from functions.profiles import get_or_load_profile
from services.profile_service import profile_service
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger
survey_router = Router()
bot = Bot(os.environ.get("BOT_TOKEN"))


async def send_daily_survey():
    clients = cache_manager.get_clients_to_survey()
    for client_id in clients:
        client_data = await profile_service.get_profile(client_id)
        client_lang = (
            cache_manager.get_profile_info_by_key(client_data.get("current_tg_id"), client_id, "language") or "ua"
        )
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        async with aiohttp.ClientSession():
            await bot.send_message(
                chat_id=client_data.get("current_tg_id"),
                text=translate(MessageText.have_you_trained, client_lang),
                reply_markup=workout_survey_keyboard(client_lang, yesterday),
                disable_notification=True,
            )

        @survey_router.callback_query(F.data.startswith("yes_"))
        @survey_router.callback_query(F.data.startswith("no_"))
        async def have_you_trained(callback_query: CallbackQuery, state: FSMContext):
            profile = await get_or_load_profile(callback_query.from_user.id)
            subscription = cache_manager.get_subscription(profile.id)
            workout_days = subscription.workout_days
            if callback_query.data.startswith("yes"):
                try:
                    day = callback_query.data.split("_")[1]
                    day_index = workout_days.index(day)
                except ValueError:
                    day_index = -1

                exercises = subscription.exercises.get(str(day_index)) or subscription.exercises.get(yesterday)
                await state.update_data(exercises=exercises, day=yesterday, day_index=day_index)
                await callback_query.answer("🔥")
                await callback_query.message.answer(
                    translate(MessageText.workout_results), reply_markup=workout_results(profile.language)
                )
                await callback_query.message.delete()
                await state.set_state(States.workout_survey)
            else:
                await callback_query.answer("😢")
                await callback_query.message.delete()


async def workout_scheduler() -> None:
    logger.debug("Starting workout scheduler ...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_survey, "cron", hour=9, minute=0)
    scheduler.start()
