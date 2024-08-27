import os
from datetime import datetime, timedelta

import loguru
from aiogram import Bot, F, Router
from aiogram.client.session import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import common.functions.chat
import common.functions.workout_plans
from bot.keyboards import workout_survey_keyboard, yes_no, workout_results
from bot.states import States
from common.functions.chat import send_message
from common.user_service import cache_manager
from texts.text_manager import MessageText, translate

logger = loguru.logger
survey_router = Router()
bot = Bot(os.environ.get("BOT_TOKEN"))


async def send_daily_survey():
    clients = cache_manager.get_clients_to_survey()
    for client_id in clients:
        client = cache_manager.get_client_by_id(client_id)
        client_lang = cache_manager.get_profile_info_by_key(client.tg_id, client_id, "language")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        async with aiohttp.ClientSession():
            await bot.send_message(
                chat_id=client.tg_id,
                text=translate(MessageText.have_you_trained, client_lang),
                reply_markup=workout_survey_keyboard(client_lang, yesterday),
                disable_notification=True,
            )

        @survey_router.callback_query(F.data.startswith("yes_"))
        @survey_router.callback_query(F.data.startswith("no_"))
        async def have_you_trained(callback_query: CallbackQuery, state: FSMContext):
            profile = cache_manager.get_current_profile(callback_query.from_user.id)
            subscription = cache_manager.get_subscription(profile.id)
            workout_days = subscription.workout_days
            if callback_query.data.startswith("yes"):
                try:
                    day = callback_query.data.split("_")[1]
                    day_index = workout_days.index(day)
                except ValueError:
                    day_index = -1

                exercises = subscription.exercises.get(str(day_index))
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


async def workout_scheduler():
    logger.info("Starting workout scheduler ...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_survey, "cron", hour=9, minute=0)
    scheduler.start()
