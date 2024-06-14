import loguru
from aiogram import F, Router
from aiogram.client.session import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.keyboards import workout_results, workout_survey_keyboard
from bot.states import States
from common.functions import bot
from common.user_service import user_session
from texts.text_manager import MessageText, translate

logger = loguru.logger
survey_router = Router()


async def send_daily_survey():
    clients = user_session.get_clients_to_survey()
    for client_id in clients:
        client = user_session.get_client_by_id(client_id)
        client_lang = user_session.get_profile_info_by_key(client.tg_id, client_id, "language")
        async with aiohttp.ClientSession():
            await bot.send_message(
                chat_id=client.tg_id,
                text=translate(MessageText.have_you_trained, client_lang),
                reply_markup=workout_survey_keyboard(client_lang),
                disable_notification=True,
            )

        @survey_router.callback_query(F.data == "yes")
        @survey_router.callback_query(F.data == "no")
        async def have_you_trained(callback_query: CallbackQuery, state: FSMContext):
            profile = user_session.get_current_profile(callback_query.from_user.id)
            if callback_query.data == "yes":
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
    await send_daily_survey()  # TODO: REMOVE
