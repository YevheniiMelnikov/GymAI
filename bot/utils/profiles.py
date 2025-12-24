from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, cast

from loguru import logger

from aiogram.types import CallbackQuery as TgCallbackQuery, Message as TgMessage

from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.bot import answer_msg, del_msg, delete_messages
from bot.utils.text import get_profile_attributes
from config.app_settings import settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.enums import ProfileStatus, WorkoutLocation
from core.schemas import Profile
from core.services.internal import APIService

from aiogram.exceptions import TelegramBadRequest

PROFILE_UPDATE_FIELDS: tuple[str, ...] = (
    "gender",
    "born_in",
    "workout_experience",
    "workout_goals",
    "workout_location",
    "health_notes",
    "diet_allergies",
    "diet_products",
    "weight",
    "height",
    "status",
    "credits",
    "gift_credits_granted",
)


def resolve_workout_location(profile: Profile) -> WorkoutLocation | None:
    location = (profile.workout_location or "").strip().lower()
    if not location:
        return None
    try:
        return WorkoutLocation(location)
    except ValueError:
        return None


if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext


async def update_profile_data(
    message: TgMessage,
    state: "FSMContext",
    bot: "Bot",
) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)

    try:

        async def create_remote_profile() -> Profile:
            profile_obj = await APIService.profile.create_profile(message.chat.id, lang)
            if profile_obj is None:
                raise ProfileNotFoundError(message.chat.id)
            payload = profile_obj.model_dump(mode="json")
            await Cache.profile.save_profile(message.chat.id, payload)
            await Cache.profile.save_record(profile_obj.id, payload)
            await state.update_data(profile=payload)
            return profile_obj

        try:
            profile = await Cache.profile.get_profile(message.chat.id)
            refreshed = await APIService.profile.get_profile(profile.id)
            if refreshed is None:
                profile = await create_remote_profile()
            else:
                profile = refreshed
        except ProfileNotFoundError:
            profile = await create_remote_profile()

        normalized_updates: dict[str, Any] = {}
        api_payload: dict[str, Any] = {}
        for field in PROFILE_UPDATE_FIELDS:
            if field not in data:
                continue
            value = data[field]
            if value is None:
                continue
            if field == "status":
                status_value = value if isinstance(value, ProfileStatus) else ProfileStatus(str(value))
                normalized_updates[field] = status_value
                api_payload[field] = status_value.value
            elif field in {"weight", "height", "credits"}:
                try:
                    numeric_value = int(value)
                except (TypeError, ValueError):
                    continue
                normalized_updates[field] = numeric_value
                api_payload[field] = numeric_value
            else:
                normalized_updates[field] = value
                api_payload[field] = value

        lang_override = data.get("lang")
        if lang_override:
            normalized_updates["language"] = lang_override
            api_payload["language"] = lang_override

        credits_delta = int(data.get("credits_delta") or 0)
        if credits_delta and not profile.gift_credits_granted:
            remaining = max(0, settings.DEFAULT_CREDITS - (profile.credits or 0))
            credits_delta_to_apply = min(credits_delta, remaining)
            if credits_delta_to_apply:
                new_credits = (profile.credits or 0) + credits_delta_to_apply
                normalized_updates["credits"] = new_credits
                api_payload["credits"] = new_credits
            normalized_updates["gift_credits_granted"] = True
            api_payload["gift_credits_granted"] = True

        if api_payload:
            update_success = await APIService.profile.update_profile(profile.id, api_payload)
            if not update_success:
                profile = await create_remote_profile()
                update_success = await APIService.profile.update_profile(profile.id, api_payload)
            if not update_success:
                raise RuntimeError(f"Failed to update profile id={profile.id}")

        updated_profile = await APIService.profile.get_profile(profile.id)
        if updated_profile is not None:
            profile = updated_profile
        elif normalized_updates:
            profile = profile.model_copy(update=normalized_updates)

        await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
        await answer_msg(message, translate(MessageText.your_data_updated, lang))
        await state.update_data(profile=profile.model_dump(mode="json"))
        pending_data = await state.get_data()
        pending_flow = pending_data.get("pending_flow")
        if pending_flow:
            await state.update_data(pending_flow=None)
            resumed = await _handle_pending_flow(message, profile, state, bot, pending_flow)
            if resumed:
                return
        from bot.utils.menus import show_main_menu

        await show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await answer_msg(message, translate(MessageText.unexpected_error, lang))

    finally:
        await del_msg(cast(TgMessage | TgCallbackQuery | None, message))


async def update_diet_preferences(
    profile: Profile,
    *,
    diet_allergies: str | None,
    diet_products: list[str] | None,
) -> Profile | None:
    api_payload: dict[str, Any] = {
        "diet_allergies": diet_allergies,
        "diet_products": diet_products,
    }
    try:
        update_success = await APIService.profile.update_profile(profile.id, api_payload)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"diet_preferences_update_failed profile_id={profile.id} error={exc}")
        return None
    if not update_success:
        logger.error(f"diet_preferences_update_failed profile_id={profile.id} error=api_rejected")
        return None
    updated = await APIService.profile.get_profile(profile.id)
    if updated is None:
        logger.warning(f"diet_preferences_refresh_failed profile_id={profile.id}")
        updated = profile.model_copy(update=api_payload)
    await Cache.profile.save_record(updated.id, updated.model_dump(mode="json"))
    return updated


async def should_grant_gift_credits(tg_id: int) -> bool:
    try:
        profile = await APIService.profile.get_profile_by_tg_id(tg_id)
    except Exception:  # noqa: BLE001
        logger.warning(f"gift_credits_check_failed tg_id={tg_id}")
        return True
    if profile is None:
        return True
    if profile.gift_credits_granted:
        return False
    return (profile.credits or 0) < settings.DEFAULT_CREDITS


async def _handle_pending_flow(
    message: Optional[TgMessage],
    profile: Profile,
    state: "FSMContext",
    bot: "Bot",
    pending_flow: dict[str, Any],
) -> bool:
    if message is None:
        return False
    flow_name = str(pending_flow.get("name") or "")
    if flow_name == "start_program_flow":
        from bot.utils.menus import start_program_flow

        await start_program_flow(message, profile, state)
        return True
    if flow_name == "start_subscription_flow":
        from bot.utils.menus import start_subscription_flow

        await start_subscription_flow(message, profile, state)
        return True
    if flow_name == "start_diet_flow":
        from bot.utils.menus import start_diet_flow

        await start_diet_flow(message, profile, state, delete_origin=False)
        return True
    if flow_name == "ask_ai_prompt":
        from bot.utils.ask_ai import start_ask_ai_prompt

        await start_ask_ai_prompt(
            message,
            profile,
            state,
            delete_origin=False,
            show_balance_menu_on_insufficient=False,
        )
        return True
    if flow_name == "show_profile":
        await _send_profile_info_after_questionnaire(message, profile, state)
        return True
    return False


async def _send_profile_info_after_questionnaire(
    message: TgMessage,
    profile: Profile,
    state: "FSMContext",
) -> None:
    lang = profile.language or settings.DEFAULT_LANG
    text = translate(MessageText.profile_info, lang).format(**get_profile_attributes(profile, lang))
    from bot.keyboards import profile_menu_kb

    profile_msg = await answer_msg(
        message,
        text,
        reply_markup=profile_menu_kb(lang, show_balance=True),
    )
    if profile_msg is not None:
        await state.update_data(chat_id=profile_msg.chat.id, message_ids=[profile_msg.message_id])
    await state.set_state(States.profile)


async def fetch_user(profile: Profile, *, refresh_if_incomplete: bool = False) -> Profile:
    try:
        user = await Cache.profile.get_record(profile.id)
    except ProfileNotFoundError:
        logger.error(
            f"ProfileNotFoundError for an existing profile {profile.id}. This might indicate data inconsistency."
        )
        raise ValueError(f"Profile data not found for existing profile id {profile.id}")

    if refresh_if_incomplete and user.status != ProfileStatus.completed:
        fresh = await APIService.profile.get_profile(profile.id)
        if fresh is not None:
            await Cache.profile.save_record(fresh.id, fresh.model_dump(mode="json"))
            return fresh
        logger.warning(f"profile_status_refresh_failed profile_id={profile.id}")
    return user


async def answer_profile(
    cbq: "TgCallbackQuery",
    profile: Profile,
    user: Profile,
    text: str,
    *,
    show_balance: bool = False,
) -> None:
    from bot.keyboards import profile_menu_kb

    message = cbq.message
    if message is None:
        return

    try:
        await message.answer(
            text,
            reply_markup=profile_menu_kb(profile.language, show_balance=show_balance),
        )
    except TelegramBadRequest as exc:
        logger.warning(f"Failed to send profile info for profile {profile.id}: {exc}")


async def get_profiles_to_survey() -> list[Profile]:
    profiles_with_workout: list[Profile] = []

    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        raw_profiles = await Cache.profile.get_all_records() or {}

        for profile_id_str in raw_profiles:
            try:
                profile_id = int(profile_id_str)
                cached_profile = await Cache.profile.get_record(profile_id)
                subscription = await Cache.workout.get_latest_subscription(cached_profile.id)
                if not subscription:
                    continue

                if not isinstance(subscription.workout_days, list):
                    logger.warning(f"Invalid workout_days format for profile_id={profile_id}")
                    continue

                if (
                    subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    profile = await APIService.profile.get_profile(cached_profile.id)
                    if profile is not None:
                        profiles_with_workout.append(profile)

            except Exception as profile_err:
                logger.warning(f"Skipping profile_id={profile_id_str} due to error: {profile_err}")
                continue

    except Exception as e:
        logger.error(f"Failed to load profiles for survey: {e}")

    return profiles_with_workout
