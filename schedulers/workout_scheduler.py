from datetime import datetime, timedelta

from common.logger import logger
from aiogram import Bot, F, Router
from aiogram.client.session import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.keyboards import workout_results_kb, workout_survey_kb
from bot.states import States
from common.settings import settings
from core.cache_manager import CacheManager
from functions.profiles import get_user_profile
from services.profile_service import ProfileService
from bot.texts.text_manager import msg_text


survey_router = Router()
bot = Bot(settings.BOT_TOKEN)


async def send_daily_survey():
    clients = CacheManager.get_clients_to_survey()
    for client_id in clients:
        client_data = await ProfileService.get_profile(client_id)
        client_lang = (
            CacheManager.get_profile_data(client_data.get("tg_id"), client_id, "language")
            or settings.DEFAULT_BOT_LANGUAGE
        )
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        async with aiohttp.ClientSession():
            await bot.send_message(
                chat_id=client_data.get("tg_id"),
                text=msg_text("have_you_trained", client_lang),
                reply_markup=workout_survey_kb(client_lang, yesterday),
                disable_notification=True,
            )

        @survey_router.callback_query(F.data.startswith("yes_"))
        @survey_router.callback_query(F.data.startswith("no_"))
        async def have_you_trained(callback_query: CallbackQuery, state: FSMContext):
            profile = await get_user_profile(callback_query.from_user.id)
            subscription = CacheManager.get_subscription(profile.id)
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
                    msg_text("workout_results", profile.language), reply_markup=workout_results_kb(profile.language)
                )
                await callback_query.message.delete()
                await state.set_state(States.workout_survey)
            else:
                await callback_query.answer("😢")
                await callback_query.message.delete()


async def run() -> None:
    logger.debug("Starting workout scheduler...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_survey, "cron", hour=9, minute=0)
    scheduler.start()
