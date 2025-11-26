import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger

from bot.keyboards import program_view_kb, workout_survey_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.profiles import get_profiles_to_survey
from config.app_settings import settings
from core.exceptions import ProfileNotFoundError, SubscriptionNotFoundError
from core.cache import Cache
from core.enums import SubscriptionPeriod, WorkoutPlanType
from bot.utils.bot import get_webapp_url
from core.services import APIService
from core.schemas import DayExercises, Profile, Subscription
from core.ai_coach.state.plan import AiPlanState
from .auth import require_internal_auth


async def _resolve_profile(profile_id: int, profile_hint: int | None) -> Profile:
    async def _fetch_from_cache(profile_key: int) -> Profile | None:
        try:
            return await Cache.profile.get_record(profile_key)
        except ProfileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cache_get_profile_failed profile_id={profile_key} err={exc!s}")
            return None

    async def _fetch_from_service(profile_key: int) -> Profile | None:
        try:
            profile = await APIService.profile.get_profile(profile_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"get_profile_failed profile_id={profile_key} err={exc!s}")
            return None
        if profile is None:
            return None
        await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
        return profile

    if profile_hint is not None and profile_hint != profile_id:
        profile = await _fetch_from_cache(profile_hint)
        if profile is None:
            profile = await _fetch_from_service(profile_hint)
        if profile is not None:
            return profile

    profile = await _fetch_from_cache(profile_id)
    if profile is None:
        profile = await _fetch_from_service(profile_id)

    if profile is None:
        raise ProfileNotFoundError(profile_id)

    return profile


def _extract_program_exercises(plan_payload_raw: dict[str, Any]) -> list[DayExercises]:
    raw_days = plan_payload_raw.get("exercises_by_day")
    if not isinstance(raw_days, list):
        raw_days = plan_payload_raw.get("exercises")
    if not isinstance(raw_days, list):
        raw_days = []
    return [day if isinstance(day, DayExercises) else DayExercises.model_validate(day) for day in raw_days]


async def _finalize_program_plan(
    *,
    plan_payload_raw: dict[str, Any],
    resolved_profile_id: int,
    profile: Profile,
    request_id: str,
    state: FSMContext,
    bot: Bot,
    state_tracker: AiPlanState,
    notify_failure: Callable[[str], Awaitable[None]],
) -> None:
    try:
        exercises_by_day = _extract_program_exercises(plan_payload_raw)
    except Exception as exc:  # noqa: BLE001
        await notify_failure(f"day_exercises_validation:{exc!s}")
        logger.error(
            f"day_exercises_validation_failed profile_id={resolved_profile_id} request_id={request_id} err={exc}"
        )
        return

    split_number = plan_payload_raw.get("split_number")
    try:
        split_value = int(split_number) if split_number is not None else len(exercises_by_day)
    except (TypeError, ValueError):
        split_value = len(exercises_by_day)

    wishes_raw = plan_payload_raw.get("wishes")
    wishes = str(wishes_raw) if wishes_raw is not None else ""

    saved_program = await APIService.workout.save_program(
        profile_id=resolved_profile_id,
        exercises=exercises_by_day,
        split_number=split_value,
        wishes=wishes,
    )
    await Cache.workout.save_program(resolved_profile_id, saved_program.model_dump(mode="json"))
    try:
        await APIService.workout.get_latest_program(resolved_profile_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"warm_program_cache_failed profile_id={resolved_profile_id} request_id={request_id} err={exc!s}")
    exercises_dump = [day.model_dump() for day in saved_program.exercises_by_day]
    program_payload = {
        "exercises": exercises_dump,
        "split": len(exercises_dump),
        "day_index": 0,
        "profile": True,
    }
    await state.update_data(**program_payload)
    await state.storage.update_data(state.key, data=program_payload)
    await state.set_state(States.program_view)
    try:
        await bot.send_message(
            chat_id=profile.tg_id,
            text=translate(MessageText.new_workout_plan, profile.language),
            reply_markup=program_view_kb(profile.language, get_webapp_url("program", profile.language)),
            disable_notification=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_plan_program_send_failed profile_id={resolved_profile_id} request_id={request_id} error={exc!s}"
        )
        await notify_failure(f"program_send_failed:{exc!s}")
        return

    await state_tracker.mark_delivered(request_id)
    logger.info(
        "AI coach plan generation finished plan_type=program "
        f"profile_id={resolved_profile_id} request_id={request_id} program_id={saved_program.id}"
    )
    return


async def _finalize_subscription_plan(
    *,
    plan_payload_raw: dict[str, Any],
    resolved_profile_id: int,
    profile: Profile,
    request_id: str,
    state: FSMContext,
    bot: Bot,
    state_tracker: AiPlanState,
    notify_failure: Callable[[str], Awaitable[None]],
    action: str,
    plan_type: WorkoutPlanType,
) -> None:
    subscription = Subscription.model_validate(plan_payload_raw)
    serialized_exercises = [day.model_dump() for day in subscription.exercises]

    if action == "update":
        try:
            current = await Cache.workout.get_latest_subscription(resolved_profile_id)
        except SubscriptionNotFoundError:
            await notify_failure("subscription_missing")
            logger.error(f"Subscription missing for update profile_id={resolved_profile_id} request_id={request_id}")
            return

        subscription_data = current.model_dump()
        subscription_data.update(
            profile=resolved_profile_id,
            exercises=serialized_exercises,
            workout_days=subscription.workout_days,
            wishes=subscription.wishes,
        )
        await APIService.workout.update_subscription(current.id, subscription_data)
        await Cache.workout.update_subscription(
            resolved_profile_id,
            {
                "exercises": serialized_exercises,
                "profile": resolved_profile_id,
                "workout_days": subscription.workout_days,
                "wishes": subscription.wishes,
            },
        )
        update_payload = {
            "exercises": serialized_exercises,
            "split": len(serialized_exercises),
            "day_index": 0,
            "profile": True,
            "subscription": True,
            "days": subscription.workout_days,
        }
        if request_id:
            update_payload["last_request_id"] = request_id
        await state.update_data(**update_payload)
        await state.storage.update_data(state.key, data=update_payload)
        await state.set_state(States.program_view)
        try:
            await bot.send_message(
                chat_id=profile.tg_id,
                text=translate(MessageText.program_updated, profile.language),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                f"ai_plan_subscription_update_notify_failed profile_id={resolved_profile_id} "
                f"request_id={request_id} error={exc!s}"
            )
            await notify_failure(f"subscription_update_send_failed:{exc!s}")
            return
        await state_tracker.mark_delivered(request_id)
        logger.info(
            "AI coach plan generation finished plan_type=subscription-update "
            f"profile_id={resolved_profile_id} request_id={request_id} subscription_id={current.id}"
        )
        return

    try:
        period_enum = SubscriptionPeriod(subscription.period)
    except ValueError:
        period_enum = SubscriptionPeriod.one_month

    price = Decimal(subscription.price)
    if price <= 0:
        price = Decimal(settings.REGULAR_AI_SUBSCRIPTION_PRICE)

    subscription_id = await APIService.workout.create_subscription(
        profile_id=resolved_profile_id,
        workout_days=subscription.workout_days,
        wishes=subscription.wishes,
        amount=price,
        period=period_enum,
        exercises=serialized_exercises,
    )
    if subscription_id is None:
        await notify_failure("subscription_create_failed")
        logger.error(
            "Subscription create failed "
            f"profile_id={resolved_profile_id} request_id={request_id} plan_type={plan_type.value}"
        )
        return

    subscription_dump = subscription.model_dump(mode="json")
    subscription_dump.update(
        id=subscription_id,
        profile=resolved_profile_id,
        exercises=serialized_exercises,
    )
    await Cache.workout.save_subscription(resolved_profile_id, subscription_dump)
    update_payload = {
        "subscription": True,
        "exercises": serialized_exercises,
        "split": len(serialized_exercises),
        "day_index": 0,
        "profile": True,
        "days": subscription.workout_days,
    }
    if request_id:
        update_payload["last_request_id"] = request_id
    await state.update_data(**update_payload)
    await state.storage.update_data(state.key, data=update_payload)
    await state.set_state(States.program_view)
    try:
        await bot.send_message(
            chat_id=profile.tg_id,
            text=translate(MessageText.subscription_created, profile.language),
            reply_markup=program_view_kb(profile.language, get_webapp_url("subscription", profile.language)),
            disable_notification=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ai_plan_subscription_create_notify_failed "
            f"profile_id={resolved_profile_id} request_id={request_id} error={exc}"
        )
        await notify_failure(f"subscription_create_send_failed:{exc!s}")
        return
    await state_tracker.mark_delivered(request_id)
    logger.info(
        f"AI coach plan generation finished plan_type=subscription-create profile_id={resolved_profile_id} "
        f"request_id={request_id} subscription_id={subscription_id}"
    )
    return


async def _process_ai_plan_ready(
    *,
    request: web.Request,
    payload: dict[str, Any],
    request_id: str,
    status: str,
    action: str,
    plan_type: WorkoutPlanType,
    profile_id: int,
    profile_hint: int | None,
) -> None:
    state_tracker = AiPlanState.create()
    bot: Bot = request.app["bot"]
    dispatcher = request.app.get("dp")
    try:
        payload_profile_id = profile_hint
        profile = await _resolve_profile(profile_id, profile_hint)
        resolved_profile_id = profile.id
        if payload_profile_id is not None and payload_profile_id != resolved_profile_id:
            logger.warning(
                "AI coach callback profile mismatch "
                f"profile_id={resolved_profile_id} payload_profile={payload_profile_id}"
            )

        if not await state_tracker.claim_delivery(request_id):
            logger.debug(
                "AI coach plan callback ignored because delivery already claimed "
                f"plan_type={plan_type.value} profile_id={resolved_profile_id} request_id={request_id}"
            )
            return

        if dispatcher is None:
            await state_tracker.mark_failed(request_id, "dispatcher_missing")
            logger.error("Dispatcher not available for AI coach plan delivery")
            return

        storage = dispatcher.storage
        state_key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
        state = FSMContext(storage=storage, key=state_key)

        state_data = await state.get_data()
        if request_id and state_data.get("last_request_id") == request_id:
            logger.debug(
                "AI coach plan callback ignored because FSM already handled request "
                f"plan_type={plan_type.value} profile_id={resolved_profile_id} request_id={request_id}"
            )
            return

        async def notify_failure(detail: str) -> None:
            first_attempt = await state_tracker.mark_failed(request_id, detail)
            if not first_attempt:
                logger.debug(
                    f"ai_plan_failure_already_notified action={action} "
                    f"profile_id={resolved_profile_id} request_id={request_id} detail={detail}"
                )
                return
            message = translate(MessageText.coach_agent_error, profile.language).format(tg=settings.TG_SUPPORT_CONTACT)
            try:
                await bot.send_message(chat_id=profile.tg_id, text=message)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"ai_plan_failure_user_message_failed action={action} "
                    f"profile_id={resolved_profile_id} request_id={request_id} error={exc!s}"
                )

        if status != "success":
            error_reason = str(payload.get("error", "unknown_error"))
            await notify_failure(error_reason)
            logger.error(
                f"AI coach plan callback returned failure plan_type={plan_type.value} "
                f"profile_id={resolved_profile_id} request_id={request_id} reason={error_reason}"
            )
            return

        plan_payload_raw = payload.get("plan")
        if not isinstance(plan_payload_raw, dict):
            await notify_failure("plan_payload_missing")
            logger.error(f"Plan payload missing profile_id={resolved_profile_id} request_id={request_id}")
            return

        profile_dump = profile.model_dump()

        await state.clear()
        base_state: dict[str, object] = {"profile": profile_dump}
        if request_id:
            base_state["last_request_id"] = request_id
        await state.update_data(**base_state)

        if plan_type is WorkoutPlanType.PROGRAM:
            await _finalize_program_plan(
                plan_payload_raw=plan_payload_raw,
                resolved_profile_id=resolved_profile_id,
                profile=profile,
                request_id=request_id,
                state=state,
                bot=bot,
                state_tracker=state_tracker,
                notify_failure=notify_failure,
            )
            return

        await _finalize_subscription_plan(
            plan_payload_raw=plan_payload_raw,
            resolved_profile_id=resolved_profile_id,
            profile=profile,
            request_id=request_id,
            state=state,
            bot=bot,
            state_tracker=state_tracker,
            notify_failure=notify_failure,
            action=action,
            plan_type=plan_type,
        )
        return
    except ProfileNotFoundError:
        await state_tracker.mark_failed(request_id, "profile_not_found")
        logger.error(f"Profile fetch failed profile_id={profile_id} request_id={request_id}: not found")
    except Exception as exc:  # noqa: BLE001
        await state_tracker.mark_failed(request_id, f"handler_exception:{exc!s}")
        logger.exception(
            "AI coach plan callback processing failed "
            f"plan_type={plan_type.value} profile_id={resolved_profile_id} request_id={request_id} error={exc!s}"
        )


@require_internal_auth
async def internal_send_daily_survey(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        profiles = await get_profiles_to_survey()
    except Exception as e:
        logger.error(f"Unexpected error in retrieving profiles: {e}")
        return web.json_response({"detail": str(e)}, status=500)

    if not profiles:
        logger.info("No profiles to survey today")
        return web.json_response({"result": "no_profiles"})

    now = datetime.now(ZoneInfo(settings.TIME_ZONE))
    yesterday = (now - timedelta(days=1)).strftime("%A").lower()

    for user_profile in profiles:
        try:
            await bot.send_message(
                chat_id=user_profile.tg_id,
                text=translate(MessageText.have_you_trained, user_profile.language),
                reply_markup=workout_survey_kb(user_profile.language, yesterday),
                disable_notification=True,
            )
            logger.info(f"Survey sent to profile {user_profile.id}")
        except Exception as e:
            logger.error(f"Survey push failed for profile_id={user_profile.id}: {e}")

    return web.json_response({"result": "ok"})


@require_internal_auth
async def internal_ai_coach_plan_ready(request: web.Request) -> web.Response:
    try:
        raw_payload = await request.json()
    except Exception:
        logger.error("ai_plan_ready_invalid_json")
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    if not isinstance(raw_payload, dict):
        logger.error("ai_plan_ready_invalid_payload_type")
        return web.json_response({"detail": "Invalid payload"}, status=400)

    payload: dict[str, Any] = raw_payload
    request_id = str(payload.get("request_id") or "")
    if not request_id:
        logger.error("ai_plan_ready_validation_failed reason=missing_request_id")
        return web.json_response({"detail": "request_id required"}, status=400)

    status = str(payload.get("status", "success"))
    action = str(payload.get("action", "create"))

    try:
        plan_type = WorkoutPlanType(payload["plan_type"])
    except KeyError:
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=plan_type_missing")
        return web.json_response({"detail": "plan_type required"}, status=400)
    except Exception:
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=invalid_plan_type")
        return web.json_response({"detail": "Invalid plan_type"}, status=400)

    profile_id_raw = payload.get("profile_id")
    if profile_id_raw is None:
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=missing_profile_id")
        return web.json_response({"detail": "profile_id required"}, status=400)
    try:
        profile_id = int(profile_id_raw)
    except (TypeError, ValueError):
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=invalid_profile_id")
        return web.json_response({"detail": "Invalid profile_id"}, status=400)

    profile_hint: int | None = None
    if "profile_id" in payload:
        try:
            profile_hint = int(payload["profile_id"])
        except (TypeError, ValueError):
            logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=invalid_profile_id")
            return web.json_response({"detail": "Invalid profile_id"}, status=400)

    async def _runner() -> None:
        try:
            await _process_ai_plan_ready(
                request=request,
                payload=payload,
                request_id=request_id,
                status=status,
                action=action,
                plan_type=plan_type,
                profile_id=profile_id,
                profile_hint=profile_hint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"ai_plan_ready_runner_failed action={action} request_id={request_id} err={exc!s}")
            state = AiPlanState.create()
            await state.mark_failed(request_id, f"runner_exception:{exc!s}")

    asyncio.create_task(_runner(), name=f"ai-plan-ready-{request_id}")
    return web.json_response({"result": "accepted"}, status=202)
