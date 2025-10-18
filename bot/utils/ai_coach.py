from celery import chain
from pydantic import ValidationError
from loguru import logger

from core.cache import Cache
from core.enums import WorkoutPlanType, WorkoutType
from core.schemas import Client, DayExercises, Program, Subscription, Profile
from core.services.internal import APIService
from core.ai_coach_payloads import AiAttachmentPayload, AiPlanGenerationPayload, AiPlanUpdatePayload, AiQuestionPayload


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
        await Cache.workout.save_program(client.id, plan.model_dump())
        return plan.exercises_by_day
    assert isinstance(plan, Subscription)
    await Cache.workout.save_subscription(client.id, plan.model_dump())
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
    client_profile_raw = getattr(client, "profile", None)
    client_profile_id = int(client_profile_raw) if client_profile_raw is not None else 0
    if client_profile_id <= 0:
        logger.error(f"ai_plan_generate_missing_profile client_id={client.id} request_id={request_id}")
        return False

    try:
        payload_model = AiPlanGenerationPayload(
            client_id=client.id,
            client_profile_id=client_profile_id,
            language=language,
            plan_type=plan_type,
            workout_type=workout_type,
            wishes=wishes,
            period=period,
            workout_days=workout_days or [],
            request_id=request_id,
        )
    except ValidationError as exc:
        logger.error(f"ai_plan_generate_invalid_payload request_id={request_id} client_id={client.id} error={exc!s}")
        return False

    try:
        from core.tasks.ai_coach import (
            generate_ai_workout_plan,
            handle_ai_plan_failure,
            notify_ai_plan_ready_task,
        )
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "client_id": client.id,
        "plan_type": plan_type.value,
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    generate_sig = generate_ai_workout_plan.s(payload).set(**options)
    notify_sig = notify_ai_plan_ready_task.s().set(queue="ai_coach", routing_key="ai_coach", headers=headers)
    failure_sig = handle_ai_plan_failure.s(payload, "create").set(queue="ai_coach", routing_key="ai_coach")

    logger.debug(
        f"dispatch_generate_plan request_id={request_id} "
        f"client_id={client.id} plan_type={plan_type.value} headers={headers}"
    )

    try:
        async_result = chain(generate_sig, notify_sig).apply_async(link_error=[failure_sig])
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client.id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc!s}"
        )
        return False

    logger.info(
        f"ai_plan_generate_enqueued request_id={request_id} task_id={async_result.id} "
        f"client_id={client.id} plan_type={plan_type.value}"
    )
    return True


async def enqueue_ai_question(
    *,
    client: Client,
    profile: Profile,
    prompt: str,
    language: str,
    request_id: str,
    image_base64: str | None = None,
    image_mime: str | None = None,
) -> bool:
    client_profile_id = int(getattr(client, "profile", profile.id))
    if client_profile_id <= 0:
        logger.error(
            "event=ask_ai_invalid_profile request_id=%s client_id=%s profile_hint=%s",
            request_id,
            client.id,
            getattr(profile, "id", None),
        )
        return False

    attachments: list[AiAttachmentPayload] = []
    if image_base64 and image_mime:
        attachments.append(AiAttachmentPayload(mime=image_mime, data_base64=image_base64))

    try:
        payload_model = AiQuestionPayload(
            client_id=client.id,
            client_profile_id=client_profile_id,
            language=language,
            prompt=prompt,
            attachments=attachments,
            request_id=request_id,
        )
    except ValidationError as exc:
        logger.error(
            "event=ask_ai_invalid_payload request_id=%s client_id=%s error=%s",
            request_id,
            client.id,
            exc,
        )
        return False

    try:
        from core.tasks.ai_coach import (
            ask_ai_question,
            handle_ai_question_failure,
            notify_ai_answer_ready_task,
        )
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"event=ask_ai_task_import_failed request_id={request_id} error={exc}")
        return False

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "client_id": client.id,
        "action": "ask_ai",
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    ask_sig = ask_ai_question.s(payload).set(**options)
    notify_sig = notify_ai_answer_ready_task.s().set(queue="ai_coach", routing_key="ai_coach", headers=headers)
    failure_sig = handle_ai_question_failure.s(payload).set(queue="ai_coach", routing_key="ai_coach")

    try:
        async_result = chain(ask_sig, notify_sig).apply_async(link_error=[failure_sig])
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "event=ask_ai_dispatch_failed request_id=%s client_id=%s error=%s",
            request_id,
            client.id,
            exc,
        )
        return False

    logger.info(
        "event=ask_ai_enqueued request_id=%s task_id=%s client_id=%s profile_id=%s",
        request_id,
        async_result.id,
        client.id,
        client_profile_id,
    )
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
        payload_model = AiPlanUpdatePayload(
            client_id=client_id,
            client_profile_id=client_profile_id,
            language=language,
            plan_type=plan_type,
            expected_workout_result=expected_workout_result,
            feedback=feedback,
            workout_type=workout_type,
            request_id=request_id,
        )
    except ValidationError as exc:
        logger.error(f"ai_plan_update_invalid_payload request_id={request_id} client_id={client_id} error={exc!s}")
        return False

    try:
        from core.tasks.ai_coach import (
            handle_ai_plan_failure,
            notify_ai_plan_ready_task,
            update_ai_workout_plan,
        )
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "client_id": client_id,
        "plan_type": plan_type.value,
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    update_sig = update_ai_workout_plan.s(payload).set(**options)
    notify_sig = notify_ai_plan_ready_task.s().set(queue="ai_coach", routing_key="ai_coach", headers=headers)
    failure_sig = handle_ai_plan_failure.s(payload, "update").set(queue="ai_coach", routing_key="ai_coach")

    logger.debug(
        f"dispatch_update_plan request_id={request_id} client_id={client_id} "
        f"plan_type={plan_type.value} headers={headers}"
    )

    try:
        async_result = chain(update_sig, notify_sig).apply_async(link_error=[failure_sig])
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc!s}"
        )
        return False

    logger.info(
        f"ai_plan_update_enqueued request_id={request_id} task_id={async_result.id} "
        f"client_id={client_id} plan_type={plan_type.value}"
    )
    return True
