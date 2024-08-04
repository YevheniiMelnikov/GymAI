from typing import Any

from aiogram import F, Router
from aiogram.enums import ParseMode

from bot.keyboards import *
from bot.keyboards import new_coach_request
from common.file_manager import avatar_manager
from common.functions.exercises import edit_subscription_exercises
from common.functions.menus import show_exercises_menu, show_manage_subscription_menu
from common.functions.text_utils import format_new_client_message, get_client_page, get_workout_types
from common.functions.utils import *
from common.models import Coach, Profile
from texts.text_manager import MessageText, translate

logger = loguru.logger
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")
OWNER_ID = os.environ.get("OWNER_ID")
sub_router = Router()


async def contact_client(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    await callback_query.answer()
    await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
    await callback_query.message.delete()
    coach = user_service.storage.get_coach_by_id(profile.id)
    await state.clear()
    await state.update_data(recipient_id=client_id, sender_name=coach.name)
    await state.set_state(States.contact_client)


async def client_request(coach: Coach, client: Client, state: FSMContext) -> None:
    data = await state.get_data()
    coach_lang = user_service.storage.get_profile_info_by_key(coach.tg_id, coach.id, "language")
    client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
    await state.update_data(recipient_language=coach_lang)

    workout_types = await get_workout_types(coach_lang)
    preferable_workout_type = data.get("workout_type")
    service = data.get("request_type")
    preferable_workouts_type = workout_types.get(preferable_workout_type, "unknown")
    subscription = user_service.storage.get_subscription(client.id)
    waiting_program = user_service.storage.check_payment_status(client.id, "program")
    waiting_subscription = user_service.storage.check_payment_status(client.id, "subscription")
    status = True if waiting_program or waiting_subscription else False
    client_data = await get_client_page(client, coach_lang, subscription, status, state)
    text = await format_new_client_message(data, coach_lang, client_lang, preferable_workouts_type)
    reply_markup = (
        new_incoming_request(coach_lang, client.id)
        if data.get("new_client")
        else incoming_request(coach_lang, service, client.id)
    )

    await send_message(
        recipient=coach,
        text=text,
        state=state,
        include_incoming_message=False,
    )

    await send_message(
        recipient=coach,
        text=translate(MessageText.client_page, coach_lang).format(**client_data),
        state=state,
        reply_markup=reply_markup,
        include_incoming_message=False,
    )


async def notify_about_new_coach(tg_id: int, profile: Profile, data: dict[str, Any]) -> None:
    name = data.get("name")
    experience = data.get("work_experience")
    info = data.get("additional_info")
    payment = data.get("payment_details")
    file_name = data.get("profile_photo")
    photo = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{file_name}"
    user = await bot.get_chat(tg_id)
    contact = f"@{user.username}" if user.username else tg_id
    async with aiohttp.ClientSession():
        await bot.send_photo(
            OWNER_ID,
            photo,
            caption=translate(MessageText.new_coach_request, "ru").format(
                name=name, experience=experience, info=info, payment=payment, contact=contact, profile_id=profile.id
            ),
            reply_markup=new_coach_request(),
        )

    @sub_router.callback_query(F.data == "coach_approve")
    async def approve_coach(callback_query: CallbackQuery, state: FSMContext):
        token = user_service.storage.get_profile_info_by_key(tg_id, profile.id, "auth_token")
        await user_service.edit_profile(profile.id, {"verified": True}, token)
        user_service.storage.set_coach_data(str(profile.id), {"verified": True})
        await callback_query.answer("👍")
        coach = user_service.storage.get_coach_by_id(profile.id)
        await send_message(
            coach, translate(MessageText.coach_verified, lang=profile.language), state, include_incoming_message=False
        )
        await callback_query.message.delete()
        logger.info(f"Coach verification for profile_id {profile.id} approved")

    @sub_router.callback_query(F.data == "coach_decline")
    async def decline_coach(callback_query: CallbackQuery, state: FSMContext):
        await callback_query.answer("👎")
        coach = user_service.storage.get_coach_by_id(profile.id)
        await send_message(
            coach, translate(MessageText.coach_declined, lang=profile.language), state, include_incoming_message=False
        )
        await callback_query.message.delete()
        logger.info(f"Coach verification for profile_id {profile.id} declined")


async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext,
    reply_markup=None,
    include_incoming_message: bool = True,
    photo=None,
) -> None:
    data = await state.get_data()
    language = data.get("recipient_language", "ua")

    if include_incoming_message:
        formatted_text = translate(MessageText.incoming_message, language).format(
            name=data.get("sender_name", ""), message=text
        )
    else:
        formatted_text = text

    async with aiohttp.ClientSession():
        if photo:
            await bot.send_photo(
                chat_id=recipient.tg_id,
                photo=photo.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=recipient.tg_id,
                text=formatted_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
            )

    @sub_router.callback_query(F.data == "quit")
    @sub_router.callback_query(F.data == "later")
    async def close_notification(callback_query: CallbackQuery):
        await callback_query.message.delete()

    @sub_router.callback_query(F.data == "view")
    async def view_subscription(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        subscription_data = user_service.storage.get_subscription(profile.id)
        await state.update_data(
            exercises=subscription_data.exercises,
            split=len(subscription_data.workout_days),
            days=subscription_data.workout_days,
        )
        await show_exercises_menu(callback_query, state, profile)

    @sub_router.callback_query(F.data.startswith("answer"))
    async def answer_message(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        sender = (
            user_service.storage.get_client_by_id(profile.id)
            if profile.status == "client"
            else user_service.storage.get_coach_by_id(profile.id)
        )
        await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
        await state.clear()
        status_to_set = States.contact_coach if profile.status == "client" else States.contact_client
        recipient_id = int(callback_query.data.split("_")[1])
        await state.update_data(recipient_id=recipient_id, sender_name=sender.name)
        await state.set_state(status_to_set)

    @sub_router.callback_query(F.data == "prev_day")
    @sub_router.callback_query(F.data == "next_day")
    async def navigate_days(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        program = user_service.storage.get_program(str(profile.id))

        if program:
            split_number = program.split_number
            exercises = program.exercises_by_day
        else:
            subscription = user_service.storage.get_subscription(str(profile.id))
            split_number = len(subscription.workout_days)
            exercises = subscription.exercises

        await state.update_data(exercises=exercises, split=split_number, client=True)
        await program_menu_pagination(state, callback_query)

    @sub_router.callback_query(F.data.startswith("edit_"))
    async def edit_subscription(callback_query: CallbackQuery, state: FSMContext):
        await edit_subscription_exercises(callback_query, state)

    @sub_router.callback_query(F.data.startswith("create"))
    async def create_workouts(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        await state.clear()
        service = callback_query.data.split("_")[1]
        client_id = callback_query.data.split("_")[2]
        await state.update_data(client_id=client_id)
        if service == "subscription":
            await show_manage_subscription_menu(callback_query, profile.language, client_id, state)
        else:
            await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
            await state.set_state(States.workouts_number)
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()
