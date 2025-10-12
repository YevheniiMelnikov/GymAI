import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger

from bot.keyboards import program_view_kb, workout_survey_kb
from bot.states import States
from bot.texts.text_manager import msg_text
from bot.utils.profiles import get_clients_to_survey
from config.app_settings import settings
from core.exceptions import ClientNotFoundError, SubscriptionNotFoundError
from core.containers import get_container
from core.cache import Cache
from core.enums import CoachType, SubscriptionPeriod, WorkoutPlanType
from bot.utils.chat import send_message
from bot.utils.bot import get_webapp_url
from core.services import APIService
from bot.utils.ai_coach import enqueue_workout_plan_update
from core.schemas import Client, DayExercises, Profile, Subscription
from cognee.api.v1.prune import prune  # pyrefly: ignore[import-error]
from core.ai_plan_state import AiPlanState
from .auth import require_internal_auth


async def _resolve_client_and_profile(
    client_id: int,
    client_profile_id: int | None,
) -> tuple[Client, int, int]:
    profile_hint = client_profile_id
    client: Client | None = None

    if profile_hint is not None and profile_hint != client_id:
        try:
            client = await Cache.client.get_client(profile_hint)
        except ClientNotFoundError:
            try:
                client = await APIService.profile.get_client_by_profile_id(profile_hint)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"get_client_by_profile_id_failed profile_id={profile_hint} err={exc!s}")
                client = None
            else:
                if client is not None:
                    await Cache.client.save_client(profile_hint, client.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cache_get_client_failed profile_id={profile_hint} err={exc!s}")
            client = None
        if client is not None:
            profile_id = client.profile
            client_profile_pk = client.id
            return client, profile_id, client_profile_pk

    client = await APIService.profile.get_client(client_id)
    if client is None:
        raise ClientNotFoundError(client_id)

    profile_id = client.profile
    client_profile_pk = client.id
    await Cache.client.save_client(profile_id, client.model_dump(mode="json"))

    if profile_hint is not None and profile_hint not in {profile_id, client_profile_pk}:
        logger.warning(
            "client_profile_hint_mismatch "
            f"client_id={client_id} hint={profile_hint} profile_id={profile_id} "
            f"client_profile_id={client_profile_pk}"
        )
    elif profile_hint == profile_id and profile_hint != client_profile_pk:
        logger.info(
            "client_profile_hint_profile_normalized "
            f"client_id={client_id} profile_id={profile_id} client_profile_id={client_profile_pk}"
        )

    return client, profile_id, client_profile_pk


async def _process_ai_plan_ready(
    *,
    request: web.Request,
    payload: dict[str, Any],
    request_id: str,
    status: str,
    action: str,
    plan_type: WorkoutPlanType,
    client_id: int,
    client_profile_id: int | None,
) -> None:
    state_tracker = AiPlanState.create()
    bot: Bot = request.app["bot"]
    dispatcher = request.app.get("dp")
    try:
        payload_profile_id = client_profile_id
        client, resolved_profile_id, resolved_client_profile_id = await _resolve_client_and_profile(
            client_id, client_profile_id
        )
        if payload_profile_id is not None and payload_profile_id not in {
            resolved_profile_id,
            resolved_client_profile_id,
        }:
            logger.warning(
                "AI coach callback profile mismatch "
                f"client_id={client_id} payload_profile={payload_profile_id} profile_id={resolved_profile_id} "
                f"client_profile_id={resolved_client_profile_id}"
            )
        client_profile_id = resolved_client_profile_id

        profile: Profile | None = await APIService.profile.get_profile(resolved_profile_id)
        if profile is None:
            await state_tracker.mark_failed(request_id, "profile_not_found")
            logger.error(f"Profile missing for client_id={client_id} request_id={request_id}")
            return

        if not await state_tracker.claim_delivery(request_id):
            logger.debug(
                "AI coach plan callback ignored because delivery already claimed "
                f"plan_type={plan_type.value} client_id={client_id} request_id={request_id}"
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
                f"plan_type={plan_type.value} client_id={client_id} request_id={request_id}"
            )
            return

        async def notify_failure(detail: str) -> None:
            first_attempt = await state_tracker.mark_failed(request_id, detail)
            if not first_attempt:
                logger.debug(
                    f"ai_plan_failure_already_notified action={action} "
                    f"client_id={client_id} request_id={request_id} detail={detail}"
                )
                return
            message = msg_text("coach_agent_error", profile.language).format(tg=settings.TG_SUPPORT_CONTACT)
            try:
                await bot.send_message(chat_id=profile.tg_id, text=message)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"ai_plan_failure_user_message_failed action={action} "
                    f"client_id={client_id} request_id={request_id} error={exc!s}"
                )

        if status != "success":
            error_reason = str(payload.get("error", "unknown_error"))
            await notify_failure(error_reason)
            logger.error(
                "AI coach plan callback returned failure "
                f"plan_type={plan_type.value} client_id={client_id} request_id={request_id} reason={error_reason}"
            )
            return

        plan_payload_raw = payload.get("plan")
        if not isinstance(plan_payload_raw, dict):
            await notify_failure("plan_payload_missing")
            logger.error(f"Plan payload missing client_id={client_id} request_id={request_id}")
            return

        profile_dump = profile.model_dump()
        client_dump = client.model_dump()

        await state.clear()
        base_state: dict[str, object] = {"profile": profile_dump, "client": client_dump}
        if request_id:
            base_state["last_request_id"] = request_id
        await state.update_data(**base_state)

        if plan_type is WorkoutPlanType.PROGRAM:
            try:
                raw_days = plan_payload_raw.get("exercises_by_day")
                if not isinstance(raw_days, list):
                    raw_days = plan_payload_raw.get("exercises")
                if not isinstance(raw_days, list):
                    raw_days = []
                exercises_by_day: list[DayExercises] = [
                    day if isinstance(day, DayExercises) else DayExercises.model_validate(day) for day in raw_days
                ]
            except Exception as exc:  # noqa: BLE001
                await notify_failure(f"day_exercises_validation:{exc!s}")
                logger.error(
                    f"day_exercises_validation_failed client_id={client_id} request_id={request_id} err={exc!s}"
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
                client_profile_id=client_profile_id,
                exercises=exercises_by_day,
                split_number=split_value,
                wishes=wishes,
            )
            await Cache.workout.save_program(client_profile_id, saved_program.model_dump(mode="json"))
            try:
                await APIService.workout.get_latest_program(client_profile_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "warm_program_cache_failed "
                    f"client_profile_id={client_profile_id} request_id={request_id} err={exc!s}"
                )
            exercises_dump = [day.model_dump() for day in saved_program.exercises_by_day]
            await state.update_data(
                exercises=exercises_dump,
                split=len(exercises_dump),
                day_index=0,
                client=True,
            )
            await state.set_state(States.program_view)
            try:
                await bot.send_message(
                    chat_id=profile.tg_id,
                    text=msg_text("new_program", profile.language),
                    reply_markup=program_view_kb(profile.language, get_webapp_url("program")),
                    disable_notification=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"ai_plan_program_send_failed action={action} client_id={client_id} "
                    f"request_id={request_id} error={exc!s}"
                )
                await notify_failure(f"program_send_failed:{exc!s}")
                return
            await state_tracker.mark_delivered(request_id)
            logger.info(
                "AI coach plan generation finished plan_type=program "
                f"client_id={client_id} request_id={request_id} program_id={saved_program.id}"
            )
            return

        subscription = Subscription.model_validate(plan_payload_raw)
        serialized_exercises = [day.model_dump() for day in subscription.exercises]

        if action == "update":
            try:
                current = await Cache.workout.get_latest_subscription(client_profile_id)
            except SubscriptionNotFoundError:
                await notify_failure("subscription_missing")
                logger.error(f"Subscription missing for update client_id={client_id} request_id={request_id}")
                return

            subscription_data = current.model_dump()
            subscription_data.update(
                client_profile=client_profile_id,
                exercises=serialized_exercises,
                workout_days=subscription.workout_days,
                wishes=subscription.wishes,
            )
            await APIService.workout.update_subscription(current.id, subscription_data)
            await Cache.workout.update_subscription(
                client_profile_id,
                {
                    "exercises": serialized_exercises,
                    "client_profile": client_profile_id,
                    "workout_days": subscription.workout_days,
                    "wishes": subscription.wishes,
                },
            )
            update_payload = {
                "exercises": serialized_exercises,
                "split": len(serialized_exercises),
                "day_index": 0,
                "client": True,
                "subscription": True,
                "days": subscription.workout_days,
            }
            if request_id:
                update_payload["last_request_id"] = request_id
            await state.update_data(**update_payload)
            await state.set_state(States.program_view)
            try:
                await bot.send_message(
                    chat_id=profile.tg_id,
                    text=msg_text("program_updated", profile.language),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"ai_plan_subscription_update_notify_failed client_id={client_id} "
                    f"request_id={request_id} error={exc!s}"
                )
                await notify_failure(f"subscription_update_send_failed:{exc!s}")
                return
            await state_tracker.mark_delivered(request_id)
            logger.info(
                "AI coach plan generation finished plan_type=subscription-update "
                f"client_id={client_id} request_id={request_id} subscription_id={current.id}"
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
            client_profile_id=client_profile_id,
            workout_days=subscription.workout_days,
            wishes=subscription.wishes,
            amount=price,
            period=period_enum,
            exercises=serialized_exercises,
        )
        if subscription_id is None:
            await notify_failure("subscription_create_failed")
            logger.error(
                f"Subscription create failed client_id={client_id} request_id={request_id} plan_type={plan_type.value}"
            )
            return

        subscription_dump = subscription.model_dump(mode="json")
        subscription_dump.update(
            id=subscription_id,
            client_profile=client_profile_id,
            exercises=serialized_exercises,
        )
        await Cache.workout.save_subscription(client_profile_id, subscription_dump)
        update_payload = {
            "subscription": True,
            "exercises": serialized_exercises,
            "split": len(serialized_exercises),
            "day_index": 0,
            "client": True,
            "days": subscription.workout_days,
        }
        if request_id:
            update_payload["last_request_id"] = request_id
        await state.update_data(**update_payload)
        await state.set_state(States.program_view)
        try:
            await bot.send_message(
                chat_id=profile.tg_id,
                text=msg_text("subscription_created", profile.language),
                reply_markup=program_view_kb(profile.language, get_webapp_url("subscription")),
                disable_notification=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                f"ai_plan_subscription_create_notify_failed client_id={client_id} request_id={request_id} error={exc!s}"
            )
            await notify_failure(f"subscription_create_send_failed:{exc!s}")
            return
        await state_tracker.mark_delivered(request_id)
        logger.info(
            "AI coach plan generation finished plan_type=subscription-create "
            f"client_id={client_id} request_id={request_id} subscription_id={subscription_id}"
        )
    except ClientNotFoundError:
        await state_tracker.mark_failed(request_id, "client_not_found")
        logger.error(f"Client fetch failed client_id={client_id} request_id={request_id}: not found")
    except Exception as exc:  # noqa: BLE001
        await state_tracker.mark_failed(request_id, f"handler_exception:{exc!s}")
        logger.exception(
            "AI coach plan callback processing failed "
            f"plan_type={plan_type.value} client_id={client_id} request_id={request_id} error={exc!s}"
        )


@require_internal_auth
async def internal_send_daily_survey(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        clients = await get_clients_to_survey()
    except Exception as e:
        logger.error(f"Unexpected error in retrieving clients: {e}")
        return web.json_response({"detail": str(e)}, status=500)

    if not clients:
        logger.info("No clients to survey today")
        return web.json_response({"result": "no_clients"})

    now = datetime.now(ZoneInfo(settings.TIME_ZONE))
    yesterday = (now - timedelta(days=1)).strftime("%A").lower()

    for client_profile in clients:
        try:
            await bot.send_message(
                chat_id=client_profile.tg_id,
                text=msg_text("have_you_trained", client_profile.language),
                reply_markup=workout_survey_kb(client_profile.language, yesterday),
                disable_notification=True,
            )
            logger.info(f"Survey sent to profile {client_profile.id}")
        except Exception as e:
            logger.error(f"Survey push failed for profile_id={client_profile.id}: {e}")

    return web.json_response({"result": "ok"})


@require_internal_auth
async def internal_export_coach_payouts(request: web.Request) -> web.Response:
    try:
        await get_container().payment_processor().export_coach_payouts()
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Failed to export coach payouts: {e}")
        return web.json_response({"detail": str(e)}, status=500)


@require_internal_auth
async def internal_send_workout_result(request: web.Request) -> web.Response:
    """Forward workout survey result to a coach or AI system."""

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    coach_id = payload.get("coach_id")
    client_id = payload.get("client_id")
    client_workout_feedback = payload.get("text")
    expected_workout_result = payload.get("program")
    request_id = payload.get("request_id") or uuid4().hex

    if not coach_id or not client_id or client_workout_feedback is None:
        return web.json_response({"detail": "Missing parameters"}, status=400)

    bot: Bot = request.app["bot"]
    coach = await Cache.coach.get_coach(int(coach_id))
    if not coach:
        return web.json_response({"detail": "Coach not found"}, status=404)

    if coach.coach_type == CoachType.ai_coach:
        client = await Cache.client.get_client(int(client_id))
        profile = await APIService.profile.get_profile(client.profile)
        language = profile.language if profile else settings.DEFAULT_LANG
        client_profile_pk = client.id
        client_profile_id = client.profile
        queued = await enqueue_workout_plan_update(
            client_id=client_profile_pk,
            client_profile_id=client_profile_id,
            expected_workout_result=str(expected_workout_result or ""),
            feedback=str(client_workout_feedback),
            language=language,
            plan_type=WorkoutPlanType.SUBSCRIPTION,
            workout_type=None,
            request_id=request_id,
        )
        if not queued:
            logger.error(f"AI workout update dispatch failed client_id={client_id} request_id={request_id}")
            return web.json_response({"detail": "dispatch_failed"}, status=503)
        return web.json_response({"result": "queued", "request_id": request_id})
    else:
        await send_message(
            recipient=coach,
            text=str(client_workout_feedback),
            bot=bot,
            state=None,
            include_incoming_message=False,
        )

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

    client_id_raw = payload.get("client_id")
    if client_id_raw is None:
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=missing_client_id")
        return web.json_response({"detail": "client_id required"}, status=400)
    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError):
        logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=invalid_client_id")
        return web.json_response({"detail": "Invalid client_id"}, status=400)

    client_profile_id: int | None = None
    if "client_profile_id" in payload:
        try:
            client_profile_id = int(payload["client_profile_id"])
        except (TypeError, ValueError):
            logger.error(f"ai_plan_ready_validation_failed request_id={request_id} reason=invalid_client_profile_id")
            return web.json_response({"detail": "Invalid client_profile_id"}, status=400)

    async def _runner() -> None:
        try:
            await _process_ai_plan_ready(
                request=request,
                payload=payload,
                request_id=request_id,
                status=status,
                action=action,
                plan_type=plan_type,
                client_id=client_id,
                client_profile_id=client_profile_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"ai_plan_ready_runner_failed action={action} request_id={request_id} err={exc!s}")
            state = AiPlanState.create()
            await state.mark_failed(request_id, f"runner_exception:{exc!s}")

    asyncio.create_task(_runner(), name=f"ai-plan-ready-{request_id}")
    return web.json_response({"result": "accepted"}, status=202)


@require_internal_auth
async def internal_prune_cognee(request: web.Request) -> web.Response:
    """Trigger Cognee prune to cleanup local data storage."""

    try:
        await prune.prune_data()
        return web.json_response({"result": "ok"})
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Cognee prune failed: {e}")
        return web.json_response({"detail": str(e)}, status=500)
