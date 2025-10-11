import asyncio

from aiogram import Bot
from celery.result import AsyncResult
from loguru import logger

from bot.texts.text_manager import msg_text
from config.app_settings import settings
from core.cache import Cache
from core.celery_app import app as celery_app
from core.debug_celery import trace_publish
from core.enums import WorkoutPlanType, WorkoutType
from core.schemas import Client, DayExercises, Program, Subscription
from core.services.internal import APIService
from core.utils.redis_lock import get_redis_client


async def generate_workout_plan(
    *,
    client: Client,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType,
    wishes: str,
    request_id: str,
    period: str | None = None,
    workout_days: list[str] | None = None,
) -> list[DayExercises]:
    client_id: int = client.id
    logger.debug(f"generate_workout_plan request_id={request_id} client_id={client_id} type={plan_type}")
    plan = await APIService.ai_coach.create_workout_plan(
        plan_type,
        client_id=client_id,
        language=language,
        period=period,
        workout_days=workout_days,
        wishes=wishes,
        workout_type=workout_type,
        request_id=request_id,
    )
    if not plan:
        logger.error(f"Workout plan generation failed client_id={client_id}")
        return []
    if plan_type is WorkoutPlanType.PROGRAM:
        assert isinstance(plan, Program)
        await Cache.workout.save_program(client.profile, plan.model_dump())
        return plan.exercises_by_day
    assert isinstance(plan, Subscription)
    await Cache.workout.save_subscription(client.profile, plan.model_dump())
    return plan.exercises


async def process_workout_plan_result(
    *,
    client_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
    plan_type: WorkoutPlanType,
) -> Program | Subscription:
    plan = await APIService.ai_coach.update_workout_plan(
        plan_type,
        client_id=client_id,
        language=language,
        expected_workout=expected_workout_result,
        feedback=feedback,
    )
    if plan:
        return plan
    logger.error(f"Workout update failed client_id={client_id}")
    if plan_type is WorkoutPlanType.PROGRAM:
        return Program(
            id=0,
            client_profile=client_id,
            exercises_by_day=[],
            created_at=0.0,
            split_number=0,
            workout_type="",
            wishes="",
        )
    return Subscription(
        id=0,
        client_profile=client_id,
        enabled=False,
        price=0,
        workout_type="",
        wishes="",
        period="",
        workout_days=[],
        exercises=[],
        payment_date="1970-01-01",
    )


async def enqueue_workout_plan_generation(
    *,
    client: Client,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType,
    wishes: str,
    request_id: str,
    period: str | None = None,
    workout_days: list[str] | None = None,
) -> bool:
    try:
        from core.tasks import generate_ai_workout_plan  # local import to avoid circular deps
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload: dict[str, object] = {
        "client_id": client.id,
        "client_profile_id": client.profile,
        "language": language,
        "plan_type": plan_type.value,
        "workout_type": workout_type.value,
        "wishes": wishes,
        "period": period,
        "workout_days": workout_days or [],
        "request_id": request_id,
    }

    task_name: str = generate_ai_workout_plan.name
    broker_url = str(getattr(celery_app.conf, "broker_url", ""))
    payload_descriptor = ",".join(sorted(payload.keys()))
    logger.debug(
        f"dispatch_generate_plan request_id={request_id} client_id={client.id} broker={broker_url} "
        f"payload_keys={payload_descriptor}"
    )

    try:
        if settings.LOG_VERBOSE_CELERY:
            task_id = trace_publish(
                celery_app,
                queue_name="ai_coach",
                exchange_name="default",
                routing_key="ai_coach",
                task_name=task_name,
                payload=payload,
            )
        else:
            async_result: AsyncResult = celery_app.send_task(  # pyrefly: ignore[not-callable]
                task_name,
                args=(payload,),
                queue="ai_coach",
                routing_key="ai_coach",
            )
            task_id = async_result.id
        logger.debug(
            f"queued_workout_plan_generation client_id={client.id} plan_type={plan_type.value} "
            f"request_id={request_id} task_id={task_id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client.id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc}"
        )
        return False
    return True


async def enqueue_workout_plan_update(
    *,
    client_id: int,
    client_profile_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType | None,
    request_id: str,
) -> bool:
    try:
        from core.tasks import update_ai_workout_plan  # local import to avoid circular deps
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload: dict[str, object] = {
        "client_id": client_id,
        "client_profile_id": client_profile_id,
        "language": language,
        "plan_type": plan_type.value,
        "expected_workout_result": expected_workout_result,
        "feedback": feedback,
        "workout_type": workout_type.value if workout_type else None,
        "request_id": request_id,
    }

    task_name: str = update_ai_workout_plan.name
    broker_url = str(getattr(celery_app.conf, "broker_url", ""))
    payload_descriptor = ",".join(sorted(payload.keys()))
    logger.debug(
        f"dispatch_update_plan request_id={request_id} client_id={client_id} broker={broker_url} "
        f"payload_keys={payload_descriptor}"
    )

    try:
        if settings.LOG_VERBOSE_CELERY:
            task_id = trace_publish(
                celery_app,
                queue_name="ai_coach",
                exchange_name="default",
                routing_key="ai_coach",
                task_name=task_name,
                payload=payload,
            )
        else:
            async_result: AsyncResult = celery_app.send_task(  # pyrefly: ignore[not-callable]
                task_name,
                args=(payload,),
                queue="ai_coach",
                routing_key="ai_coach",
            )
            task_id = async_result.id
        logger.debug(
            f"queued_workout_plan_update client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} task_id={task_id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc}"
        )
        return False
    return True


async def _notify_plan_failure(
    *,
    bot: Bot,
    chat_id: int,
    language: str,
    action: str,
    request_id: str,
    detail: str,
) -> None:
    client = get_redis_client()
    reported_key = f"ai:plan:failure_notified:{request_id}"
    try:
        reported = bool(
            await client.set(
                reported_key,
                "1",
                nx=True,
                ex=settings.AI_PLAN_NOTIFY_FAILURE_TTL,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"ai_plan_failure_flag_skip request_id={request_id} error={exc!s}")
        reported = True
    if not reported:
        logger.info(f"ai_plan_failure_notification_skipped request_id={request_id} already_reported=1")
        return

    message = msg_text("coach_agent_error", language).format(tg=settings.TG_SUPPORT_CONTACT)
    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"ai_plan_failure_user_message_failed request_id={request_id} error={exc!s}")
    logger.error(f"ai_plan_failure_notified action={action} request_id={request_id} detail={detail}")


async def _watch_plan_delivery(
    *,
    bot: Bot,
    chat_id: int,
    language: str,
    action: str,
    request_id: str,
) -> None:
    if not request_id:
        return
    client = get_redis_client()
    delivered_key = f"ai:plan:delivered:{request_id}"
    failure_key = f"ai:plan:notify_failed:{request_id}"
    poll_interval = max(1, settings.AI_PLAN_NOTIFY_POLL_INTERVAL)
    notify_backoff = 0
    notify_retries = 0
    try:
        from core.tasks import notify_ai_plan_ready_task  # local import to avoid circular deps

        raw_backoff = getattr(notify_ai_plan_ready_task, "retry_backoff", 0) or 0
        notify_retries = int(getattr(notify_ai_plan_ready_task, "max_retries", 0) or 0)
        if isinstance(raw_backoff, (int, float)) and raw_backoff > 0:
            notify_backoff = int(raw_backoff)
    except Exception:
        notify_backoff = 0
        notify_retries = 0
    if notify_backoff <= 0:
        notify_backoff = 30
    notify_window = 0
    if notify_retries > 0:
        step = notify_backoff
        for _ in range(notify_retries):
            notify_window += step
            step *= 2
    timeout = max(
        settings.AI_PLAN_NOTIFY_TIMEOUT,
        settings.AI_COACH_TIMEOUT + notify_window + 120,
        poll_interval,
    )
    elapsed = 0
    logger.debug(f"ai_plan_watch_start action={action} request_id={request_id} timeout={timeout}")
    try:
        while elapsed < timeout:
            delivered = bool(await client.exists(delivered_key))
            if delivered:
                logger.debug(f"ai_plan_watch_done action={action} request_id={request_id} status=delivered")
                return
            failure_detail_raw = await client.get(failure_key)
            if isinstance(failure_detail_raw, (bytes, bytearray)):
                failure_detail = failure_detail_raw.decode("utf-8", errors="replace")
            else:
                failure_detail = failure_detail_raw
            if failure_detail:
                await _notify_plan_failure(
                    bot=bot,
                    chat_id=chat_id,
                    language=language,
                    action=action,
                    request_id=request_id,
                    detail=str(failure_detail),
                )
                return
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        logger.warning(
            f"ai_plan_watch_timeout action={action} request_id={request_id} elapsed={elapsed} timeout={timeout}"
        )
        await _notify_plan_failure(
            bot=bot,
            chat_id=chat_id,
            language=language,
            action=action,
            request_id=request_id,
            detail="timeout",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"ai_plan_watch_failed action={action} request_id={request_id} error={exc!s}")


def schedule_ai_plan_notification_watch(
    *,
    bot: Bot,
    chat_id: int,
    language: str,
    action: str,
    request_id: str,
) -> None:
    if not request_id:
        return

    async def _runner() -> None:
        try:
            await _watch_plan_delivery(
                bot=bot,
                chat_id=chat_id,
                language=language,
                action=action,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"ai_plan_watch_runner_failed action={action} request_id={request_id} error={exc!s}")

    asyncio.create_task(_runner(), name=f"ai-plan-watch-{request_id}")
