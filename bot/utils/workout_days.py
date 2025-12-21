from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from bot.keyboards import workout_days_selection_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.bot import answer_msg, del_msg
from core.enums import SubscriptionPeriod

WORKOUT_DAYS_PLUS = "workout_days_plus"
WORKOUT_DAYS_MINUS = "workout_days_minus"
WORKOUT_DAYS_CONTINUE = "workout_days_continue"
WORKOUT_DAYS_BACK = "workout_days_back"
DEFAULT_WORKOUT_DAYS_COUNT = 3

_DIGIT_EMOJIS: dict[int, str] = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
}


def _clamp_workout_days(count: int) -> int:
    return max(1, min(7, count))


def day_labels(count: int) -> list[str]:
    capped = _clamp_workout_days(count)
    return [f"Day {index}" for index in range(1, capped + 1)]


def _digit_to_emoji(count: int) -> str:
    if count <= 0:
        return "0️⃣"
    return _DIGIT_EMOJIS.get(count, str(count))


def compose_workout_days_prompt(lang: str, count: int) -> str:
    days_label = _digit_to_emoji(count)
    return translate(MessageText.workout_days_selection, lang).format(days=days_label)


def build_workout_days_state(
    *,
    service: str,
    period_value: str | None = None,
    workout_location: str | None = None,
    count: int = DEFAULT_WORKOUT_DAYS_COUNT,
) -> dict[str, object]:
    return {
        "workout_days_count": _clamp_workout_days(count),
        "workout_days_service": service,
        "workout_days_period": period_value,
        "workout_days_location": workout_location,
    }


async def update_workout_days_message(callback_query: CallbackQuery, lang: str, count: int) -> None:
    if callback_query.message is None or not isinstance(callback_query.message, Message):
        return
    text = compose_workout_days_prompt(lang, count)
    markup = workout_days_selection_kb(lang)
    with suppress(TelegramBadRequest):
        await callback_query.message.edit_text(text, reply_markup=markup)


def _map_service_period(service: str) -> SubscriptionPeriod | None:
    return {
        "subscription_1_month": SubscriptionPeriod.one_month,
        "subscription_6_months": SubscriptionPeriod.six_months,
        "subscription_12_months": SubscriptionPeriod.twelve_months,
    }.get(service)


def service_period_value(service: str) -> str | None:
    period = _map_service_period(service)
    return period.value if period else None


async def start_workout_days_selection(
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
        build_workout_days_state(
            service=service,
            period_value=period_value,
            workout_location=workout_location,
        )
    )
    await state.set_state(States.workout_days_selection)
    if show_wishes_prompt:
        instructions = translate(MessageText.enter_wishes, lang)
        await answer_msg(source, instructions)
    text = compose_workout_days_prompt(lang, DEFAULT_WORKOUT_DAYS_COUNT)
    await answer_msg(source, text, reply_markup=workout_days_selection_kb(lang))
    if isinstance(source, CallbackQuery):
        await del_msg(source)
