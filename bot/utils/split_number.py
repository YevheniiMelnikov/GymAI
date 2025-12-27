from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from bot.keyboards import split_number_selection_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.bot import answer_msg, del_msg
from bot.utils.prompts import send_enter_wishes_prompt
from bot.services.pricing import ServiceCatalog

SPLIT_NUMBER_PLUS = "split_number_plus"
SPLIT_NUMBER_MINUS = "split_number_minus"
SPLIT_NUMBER_CONTINUE = "split_number_continue"
SPLIT_NUMBER_BACK = "split_number_back"
DEFAULT_SPLIT_NUMBER = 3

_DIGIT_EMOJIS: dict[int, str] = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
}


def _clamp_split_number(count: int) -> int:
    return max(1, min(7, count))


def _digit_to_emoji(count: int) -> str:
    if count <= 0:
        return "0️⃣"
    return _DIGIT_EMOJIS.get(count, str(count))


def compose_split_number_prompt(lang: str, count: int) -> str:
    days_label = _digit_to_emoji(count)
    return translate(MessageText.split_number_selection, lang).format(days=days_label)


def build_split_number_state(
    *,
    service: str,
    period_value: str | None = None,
    workout_location: str | None = None,
    count: int = DEFAULT_SPLIT_NUMBER,
) -> dict[str, object]:
    return {
        "split_number": _clamp_split_number(count),
        "split_number_service": service,
        "split_number_period": period_value,
        "split_number_location": workout_location,
    }


async def update_split_number_message(callback_query: CallbackQuery, lang: str, count: int) -> None:
    if callback_query.message is None or not isinstance(callback_query.message, Message):
        return
    text = compose_split_number_prompt(lang, count)
    markup = split_number_selection_kb(lang)
    with suppress(TelegramBadRequest):
        await callback_query.message.edit_text(text, reply_markup=markup)


def service_period_value(service: str) -> str | None:
    period = ServiceCatalog.subscription_period(service)
    return period.value if period else None


async def start_split_number_selection(
    source: CallbackQuery | Message,
    state: FSMContext,
    *,
    lang: str,
    service: str,
    period_value: str | None = None,
    workout_location: str | None = None,
    show_wishes_prompt: bool = True,
) -> None:
    await state.update_data(
        build_split_number_state(
            service=service,
            period_value=period_value,
            workout_location=workout_location,
        )
    )
    await state.set_state(States.split_number_selection)
    if show_wishes_prompt:
        await send_enter_wishes_prompt(source, lang)
    text = compose_split_number_prompt(lang, DEFAULT_SPLIT_NUMBER)
    await answer_msg(source, text, reply_markup=split_number_selection_kb(lang))
    if isinstance(source, CallbackQuery):
        await del_msg(source)
