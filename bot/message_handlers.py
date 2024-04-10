import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import choose_account_type, choose_gender, codes, language_choice, main_menu_keyboard
from bot.states import States
from common.functions import create_person, edit_person, get_person
from texts.text_manager import MessageText, translate

logger = loguru.logger
main_router = Router()


@main_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    if person := await get_person(message.from_user.id):
        await message.answer(
            text=translate(MessageText.choose_language, lang=person.language), reply_markup=language_choice()
        )
        await state.set_state(States.language_choice)


@main_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    if person := await get_person(message.from_user.id):
        if not person.language:
            await state.set_state(States.language_choice)
            await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        else:
            await state.set_state(States.main_menu)
            await message.answer(
                text=translate(MessageText.welcome, lang=person.language),
                reply_markup=main_menu_keyboard(person.language),
            )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        await state.set_state(States.language_choice)


@main_router.message(States.language_choice)
async def set_language(message: Message, state: FSMContext) -> None:
    if lang_code := codes.get(message.text):
        if await get_person(message.from_user.id):
            await edit_person(message.from_user.id, {"language": lang_code})
        else:
            await state.update_data({"language": lang_code})
            await message.answer(
                text=translate(MessageText.choose_account_type, lang=lang_code),
                reply_markup=choose_account_type(lang_code),
            )
            await state.set_state(States.account_type)
            return
        await state.set_state(States.main_menu)
        await message.answer(
            text=translate(MessageText.welcome, lang=lang_code),
            reply_markup=main_menu_keyboard(lang_code),
        )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        await message.delete()


@main_router.callback_query(States.account_type)
async def set_account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback_query.message.content_type != "text":
        await state.set_state(States.account_type)
        await callback_query.message.answer(text=translate(MessageText.choose_account_type, lang=data.get("language")))
        await callback_query.message.delete()
        return

    await state.update_data({"account_type": callback_query.data})
    await state.set_state(States.short_name)
    await callback_query.message.answer(text=translate(MessageText.choose_short_name, lang=data.get("language")))


@main_router.message(States.short_name)
async def set_short_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.content_type != "text":
        await state.set_state(States.short_name)
        await message.answer(text=translate(MessageText.choose_short_name, lang=data.get("language")))
        await message.delete()
        return

    await state.update_data({"short_name": message.text})
    await message.delete()
    await state.set_state(States.password)
    await message.answer(text=translate(MessageText.choose_password, lang=data.get("language")))


@main_router.message(States.password)
async def set_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.content_type != "text":
        await state.set_state(States.short_name)
        await message.answer(text=translate(MessageText.choose_short_name, lang=data.get("language")))
        await message.delete()
        return

    await state.update_data({"password": message.text})
    await message.delete()
    await state.set_state(States.gender)
    await message.answer(text=translate(MessageText.choose_gender), reply_markup=choose_gender(data.get("language")))


@main_router.callback_query(States.gender)
async def set_gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback_query.message.content_type != "text":
        await state.set_state(States.gender)
        await callback_query.message.answer(
            text=translate(MessageText.choose_gender), reply_markup=choose_gender(data.get("language"))
        )
        await callback_query.message.delete()
        return

    await state.update_data({"gender": callback_query.data})
    await callback_query.message.delete()
    await state.set_state(States.birth_date)
    await callback_query.message.answer(text=translate(MessageText.choose_birth_date, lang=data.get("language")))


@main_router.message(States.birth_date)
async def set_birth_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.content_type != "text":
        await state.set_state(States.birth_date)
        await message.answer(text=translate(MessageText.choose_birth_date, lang=data.get("language")))
        await message.delete()
        return

    await state.update_data({"birth_date": message.text})
    await create_person(
        dict(
            tg_user_id=message.from_user.id,
            short_name=data["short_name"],
            password=data["password"],
            status=data["account_type"],
            gender=data["gender"],
            birth_date=message.text,
            language=data["language"],
        ),
    )
    await state.set_state(States.main_menu)
    await message.answer(
        text=translate(MessageText.registration_successful, lang=data.get("language")),
        reply_markup=main_menu_keyboard(data.get("language")),
    )
    await state.clear()
