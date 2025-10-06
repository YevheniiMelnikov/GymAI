from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

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
from core.schemas import Program, Profile, Subscription
from cognee.api.v1.prune import prune  # pyrefly: ignore[import-error]
from core.utils.redis_lock import get_redis_client


async def _claim_plan_delivery(request_id: str) -> bool:
    if not request_id:
        return True
    try:
        client = get_redis_client()
        key = f"ai:plan:delivered:{request_id}"
        ok = await client.set(key, "1", nx=True, ex=settings.AI_PLAN_DEDUP_TTL)
        return bool(ok)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"ai_plan_delivery_dedupe_skip request_id={request_id} error={exc!s}")
        return True


async def internal_send_daily_survey(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    bot: Bot = request.app["bot"]
    try:
        clients = await get_clients_to_survey()
    except Exception as e:
        logger.error(f"Unexpected error in retrieving clients: {e}")
        return web.json_response({"detail": str(e)}, status=500)

    if not clients:
        logger.info("No clients to survey today")
        return web.json_response({"result": "no_clients"})

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()

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


async def internal_export_coach_payouts(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        await get_container().payment_processor().export_coach_payouts()
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Failed to export coach payouts: {e}")
        return web.json_response({"detail": str(e)}, status=500)


async def internal_send_workout_result(request: web.Request) -> web.Response:
    """Forward workout survey result to a coach or AI system."""

    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

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
        queued = await enqueue_workout_plan_update(
            client_id=int(client_id),
            client_profile_id=client.profile,
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


async def internal_ai_coach_plan_ready(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    raw_request_id = payload.get("request_id")
    request_id = str(raw_request_id or "")
    status = str(payload.get("status", "success"))
    action = str(payload.get("action", "create"))

    try:
        plan_type = WorkoutPlanType(payload["plan_type"])
    except Exception:
        return web.json_response({"detail": "Invalid plan_type"}, status=400)

    client_id_raw = payload.get("client_id")
    if client_id_raw is None:
        return web.json_response({"detail": "Missing client_id"}, status=400)

    client_id = int(client_id_raw)
    client_profile_id: int | None = None
    if "client_profile_id" in payload:
        try:
            client_profile_id = int(payload["client_profile_id"])
        except (TypeError, ValueError):
            return web.json_response({"detail": "Invalid client_profile_id"}, status=400)

    try:
        if client_profile_id is not None:
            client = await Cache.client.get_client(client_profile_id)
        else:
            client = await Cache.client.get_client(client_id)
    except ClientNotFoundError:
        client = None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Client cache lookup failed client_id={client_id} request_id={request_id}: {exc}")
        client = None

    if client is None:
        client = await APIService.profile.get_client(client_id)
        if client is None:
            logger.error(f"Client fetch failed client_id={client_id} request_id={request_id}: not found")
            return web.json_response({"detail": "Client not found"}, status=404)
        await Cache.client.save_client(client.profile, client.model_dump(mode="json"))

    if client_profile_id is not None and client.profile != client_profile_id:
        logger.warning(
            f"client_profile_mismatch client_id={client_id} payload_profile={client_profile_id} actual={client.profile}"
        )
    client_profile_id = client.profile

    profile: Profile | None = await APIService.profile.get_profile(client.profile)
    if profile is None:
        logger.error(f"Profile missing for client_id={client_id} request_id={request_id}")
        return web.json_response({"detail": "Profile not found"}, status=404)

    if not await _claim_plan_delivery(request_id):
        logger.info(
            "ai_plan_delivery_duplicate "
            f"action={action} plan_type={plan_type.value} "
            f"client_id={client_id} request_id={request_id}"
        )
        return web.json_response({"result": "duplicate_ignored"})

    bot: Bot = request.app["bot"]
    dispatcher = request.app.get("dp")
    if dispatcher is None:
        logger.error("Dispatcher not available for AI coach plan delivery")
        return web.json_response({"detail": "Dispatcher unavailable"}, status=503)

    storage = dispatcher.storage
    state_key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
    state = FSMContext(storage=storage, key=state_key)

    state_data = await state.get_data()
    if request_id and state_data.get("last_request_id") == request_id:
        logger.info(
            "ai_plan_state_duplicate "
            f"action={action} plan_type={plan_type.value} "
            f"client_id={client_id} request_id={request_id}"
        )
        return web.json_response({"result": "duplicate_ignored"})

    if status != "success":
        error_reason = payload.get("error", "unknown_error")
        message = msg_text("coach_agent_error", profile.language).format(tg=settings.TG_SUPPORT_CONTACT)
        await bot.send_message(
            chat_id=profile.tg_id,
            text=message,
        )
        admin_message = (
            "AI plan failed "
            f"action={action} plan_type={plan_type.value} "
            f"client_id={client_id} request_id={request_id} "
            f"reason={error_reason}"
        )
        await bot.send_message(settings.ADMIN_ID, admin_message)
        return web.json_response({"result": "notified"})

    plan_payload = payload.get("plan")
    if not isinstance(plan_payload, dict):
        logger.error(f"Plan payload missing client_id={client_id} request_id={request_id}")
        return web.json_response({"detail": "Invalid plan payload"}, status=400)

    plan_keys = ",".join(sorted(plan_payload.keys()))
    logger.info(
        f"ai_plan_payload action={action} status={status} plan_type={plan_type.value} "
        f"client_id={client_id} profile_id={client_profile_id} request_id={request_id} "
        f"plan_fields={plan_keys} plan_size={len(plan_payload)}"
    )

    profile_dump = profile.model_dump()
    client_dump = client.model_dump()

    await state.clear()
    base_state: dict[str, object] = {"profile": profile_dump, "client": client_dump}
    if request_id:
        base_state["last_request_id"] = request_id
    await state.update_data(**base_state)

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan_payload)
        saved_program = await APIService.workout.save_program(
            client_profile_id=client.profile,
            exercises=program.exercises_by_day,
            split_number=program.split_number or len(program.exercises_by_day),
            wishes=program.wishes or "",
        )
        await Cache.workout.save_program(client.profile, saved_program.model_dump(mode="json"))
        exercises_dump = [day.model_dump() for day in saved_program.exercises_by_day]
        await state.update_data(
            exercises=exercises_dump,
            split=len(exercises_dump),
            day_index=0,
            client=True,
        )
        await state.set_state(States.program_view)
        await bot.send_message(
            chat_id=profile.tg_id,
            text=msg_text("new_program", profile.language),
            reply_markup=program_view_kb(profile.language, get_webapp_url("program")),
            disable_notification=True,
        )
        return web.json_response({"result": "delivered"})

    subscription = Subscription.model_validate(plan_payload)
    serialized_exercises = [day.model_dump() for day in subscription.exercises]

    if action == "update":
        try:
            current = await Cache.workout.get_latest_subscription(client.profile)
        except SubscriptionNotFoundError:
            logger.error(f"Subscription missing for update client_id={client_id} request_id={request_id}")
            return web.json_response({"detail": "Subscription not found"}, status=404)

        subscription_data = current.model_dump()
        subscription_data.update(
            client_profile=client.profile,
            exercises=serialized_exercises,
            workout_days=subscription.workout_days,
            wishes=subscription.wishes,
        )
        await APIService.workout.update_subscription(current.id, subscription_data)
        await Cache.workout.update_subscription(
            client.profile,
            {
                "exercises": serialized_exercises,
                "client_profile": client.profile,
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
        await bot.send_message(
            chat_id=profile.tg_id,
            text=msg_text("program_updated", profile.language),
            parse_mode=ParseMode.HTML,
        )
        return web.json_response({"result": "updated"})

    try:
        period_enum = SubscriptionPeriod(subscription.period)
    except ValueError:
        period_enum = SubscriptionPeriod.one_month

    price = Decimal(subscription.price)
    if price <= 0:
        price = Decimal(settings.REGULAR_AI_SUBSCRIPTION_PRICE)

    subscription_id = await APIService.workout.create_subscription(
        client_profile_id=client.profile,
        workout_days=subscription.workout_days,
        wishes=subscription.wishes,
        amount=price,
        period=period_enum,
        exercises=serialized_exercises,
    )
    if subscription_id is None:
        logger.error(
            f"Subscription create failed client_id={client_id} request_id={request_id} plan_type={plan_type.value}"
        )
        return web.json_response({"detail": "subscription_create_failed"}, status=502)

    subscription_dump = subscription.model_dump(mode="json")
    subscription_dump.update(
        id=subscription_id,
        client_profile=client.profile,
        exercises=serialized_exercises,
    )
    await Cache.workout.save_subscription(client.profile, subscription_dump)
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
    await bot.send_message(
        chat_id=profile.tg_id,
        text=msg_text("new_program", profile.language),
        reply_markup=program_view_kb(profile.language, get_webapp_url("program")),
        disable_notification=True,
    )
    return web.json_response({"result": "delivered"})


async def internal_prune_cognee(request: web.Request) -> web.Response:
    """Trigger Cognee prune to cleanup local data storage."""

    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        await prune.prune_data()
        return web.json_response({"result": "ok"})
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Cognee prune failed: {e}")
        return web.json_response({"detail": str(e)}, status=500)
