import asyncio
from typing import Any

from aiohttp import web
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger
from pydantic import ValidationError

from bot.keyboards import program_view_kb as _program_view_kb, weekly_survey_kb
from bot.texts import MessageText, translate
from bot.handlers.internal.schemas import WeeklySurveyNotify
from bot.handlers.internal.plan_finalizers import FINALIZERS, PlanFinalizeContext
from config.app_settings import settings
from core.exceptions import ProfileNotFoundError
from core.cache import Cache
from core.enums import WorkoutPlanType
from bot.utils.bot import get_webapp_url
from core.services import APIService
from core.schemas import Profile
from core.ai_coach.state.plan import AiPlanState
from .auth import require_internal_auth

program_view_kb = _program_view_kb


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
    logger.info(
        "ai_plan_ready_start action={} status={} plan_type={} profile_id={} request_id={}",
        action,
        status,
        plan_type.value,
        profile_id,
        request_id,
    )
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

        profile_dump = profile.model_dump(mode="json")

        await state.clear()
        base_state: dict[str, object] = {"profile": profile_dump}
        if plan_type is WorkoutPlanType.SUBSCRIPTION:
            base_state["subscription"] = True
        if request_id:
            base_state["last_request_id"] = request_id
        if plan_type is WorkoutPlanType.SUBSCRIPTION and action == "create":
            previous_subscription_id = payload.get("previous_subscription_id")
            if previous_subscription_id is not None:
                base_state["previous_subscription_id"] = previous_subscription_id
        if plan_type is WorkoutPlanType.SUBSCRIPTION and action == "update":
            subscription_id = payload.get("subscription_id")
            if subscription_id is not None:
                base_state["subscription_id"] = subscription_id
        await state.update_data(**base_state)

        finalizer = FINALIZERS.get(plan_type)
        if finalizer is None:
            await notify_failure("finalizer_missing")
            logger.error(
                "Finalizer missing "
                f"plan_type={plan_type.value} profile_id={resolved_profile_id} request_id={request_id}"
            )
            return
        await finalizer.finalize(
            PlanFinalizeContext(
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
async def internal_send_weekly_survey(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        raw_payload = await request.json()
    except Exception:
        logger.error("weekly_survey_invalid_json")
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    try:
        payload = WeeklySurveyNotify.model_validate(raw_payload)
    except ValidationError as exc:
        logger.error(f"weekly_survey_invalid_payload error={exc}")
        return web.json_response({"detail": "Invalid payload"}, status=400)

    if not payload.recipients:
        logger.info("weekly_survey_skipped reason=no_recipients")
        return web.json_response({"result": "no_recipients"})

    for recipient in payload.recipients:
        lang = recipient.language or settings.DEFAULT_LANG
        webapp_url = get_webapp_url("weekly_survey", lang)
        if not webapp_url:
            logger.warning(f"weekly_survey_skipped reason=missing_webapp_url profile_id={recipient.profile_id}")
            continue
        try:
            await bot.send_message(
                chat_id=recipient.tg_id,
                text=translate(MessageText.weekly_survey_prompt, lang).format(bot_name=settings.BOT_NAME),
                reply_markup=weekly_survey_kb(lang, webapp_url),
                disable_notification=True,
            )
            logger.info(f"weekly_survey_sent profile_id={recipient.profile_id}")
        except Exception as exc:
            logger.error(f"weekly_survey_failed profile_id={recipient.profile_id} error={exc!s}")

    return web.json_response({"result": "ok", "sent": len(payload.recipients)})


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
    logger.info(
        "ai_plan_ready_received action={} status={} request_id={} plan_type={} profile_id={} has_plan={}",
        action,
        status,
        request_id,
        payload.get("plan_type"),
        payload.get("profile_id"),
        "plan" in payload,
    )

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
