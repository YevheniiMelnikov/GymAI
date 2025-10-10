import os
import shutil
import subprocess
import asyncio
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

from celery import Task

from core.celery_app import app
from loguru import logger
import httpx

from config.app_settings import settings
from core.cache import Cache
from core.services import APIService
from core.services.internal.api_client import APIClientHTTPError, APIClientTransportError
from bot.texts.text_manager import msg_text
from apps.payments.tasks import send_payment_message
from bot.utils.profiles import get_assigned_coach
from core.enums import CoachType, SubscriptionPeriod, WorkoutPlanType, WorkoutType
from core.schemas import Program, Subscription
from core.utils.redis_lock import redis_try_lock, get_redis_client


def _next_payment_date(period: SubscriptionPeriod = SubscriptionPeriod.one_month) -> str:
    today = date.today()
    if period is SubscriptionPeriod.six_months:
        next_date = cast(date, today + relativedelta(months=+6))  # pyrefly: ignore[redundant-cast]
    else:
        next_date = cast(date, today + relativedelta(months=+1))  # pyrefly: ignore[redundant-cast]
    return next_date.isoformat()


# ---------- Backups ----------

_dumps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dumps")
_pg_dir = os.path.join(_dumps_dir, "postgres")
_redis_dir = os.path.join(_dumps_dir, "redis")

os.makedirs(_pg_dir, exist_ok=True)
os.makedirs(_redis_dir, exist_ok=True)


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def pg_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = os.path.join(_pg_dir, f"{settings.DB_NAME}_backup_{ts}.dump")
    cmd = [
        "pg_dump",
        "-h",
        settings.DB_HOST,
        "-p",
        settings.DB_PORT,
        "-U",
        settings.DB_USER,
        "-F",
        "c",
        settings.DB_NAME,
    ]
    try:
        with open(path, "wb") as f:
            subprocess.run(cmd, stdout=f, check=True)
        logger.info(f"Postgres backup saved {path}")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def redis_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    tmp_path = f"/tmp/redis_backup_{ts}.rdb"
    final_dst = os.path.join(_redis_dir, f"redis_backup_{ts}.rdb")

    try:
        subprocess.run(
            ["redis-cli", "-u", settings.REDIS_URL, "--rdb", tmp_path],
            check=True,
        )
        shutil.move(tmp_path, final_dst)
        logger.info(f"Redis backup saved {final_dst}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def cleanup_backups(self):
    cutoff = datetime.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")


# ---------- Billing ----------


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def deactivate_expired_subscriptions(self):
    logger.info("deactivate_expired_subscriptions started")

    async def _impl() -> None:
        today = datetime.now().date().isoformat()
        subscriptions = await APIService.payment.get_expired_subscriptions(today)

        for sub in subscriptions:
            if not sub.id or not sub.client_profile:
                logger.warning(f"Invalid subscription: {sub}")
                continue
            await APIService.workout.update_subscription(
                sub.id, {"enabled": False, "client_profile": sub.client_profile}
            )
            await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
            await Cache.payment.reset_status(sub.client_profile, "subscription")
            logger.info(f"Subscription {sub.id} deactivated for user {sub.client_profile}")

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deactivate_expired_subscriptions failed: {exc}")
        raise
    logger.info("deactivate_expired_subscriptions completed")


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def warn_low_credits(self):
    logger.info("warn_low_credits started")

    async def _impl() -> None:
        tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
        subs = await APIService.payment.get_expired_subscriptions(tomorrow)
        for sub in subs:
            if not sub.client_profile:
                continue
            client = await Cache.client.get_client(sub.client_profile)
            profile = await APIService.profile.get_profile(client.profile)
            required = int(sub.price)
            if client.credits < required:
                lang = profile.language if profile else settings.DEFAULT_LANG
                send_payment_message.delay(  # pyrefly: ignore[not-callable]
                    sub.client_profile,
                    msg_text("not_enough_credits", lang),
                )

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"warn_low_credits failed: {exc}")
        raise
    logger.info("warn_low_credits completed")


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def charge_due_subscriptions(self):
    logger.info("charge_due_subscriptions started")

    async def _impl() -> None:
        today = datetime.now().date().isoformat()
        subs = await APIService.payment.get_expired_subscriptions(today)
        for sub in subs:
            if not sub.id or not sub.client_profile:
                continue
            client = await Cache.client.get_client(sub.client_profile)
            required = int(sub.price)
            if client.credits < required:
                await APIService.workout.update_subscription(
                    sub.id, {"enabled": False, "client_profile": sub.client_profile}
                )
                await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
                await Cache.payment.reset_status(sub.client_profile, "subscription")
                continue

            await APIService.profile.adjust_client_credits(client.profile, -required)
            await Cache.client.update_client(client.profile, {"credits": client.credits - required})
            if client.assigned_to:
                coach = await get_assigned_coach(client, coach_type=CoachType.human)
                if coach:
                    payout = (Decimal(sub.price) * settings.CREDIT_RATE_MAX_PACK).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                    await APIService.profile.adjust_coach_payout_due(coach.profile, payout)
                    new_due = (coach.payout_due or Decimal("0")) + payout
                    await Cache.coach.update_coach(coach.profile, {"payout_due": str(new_due)})
            period_str = getattr(sub, "period", SubscriptionPeriod.one_month.value)
            period = SubscriptionPeriod(period_str)
            next_date = _next_payment_date(period)
            await APIService.workout.update_subscription(sub.id, {"payment_date": next_date})
            await Cache.workout.update_subscription(sub.client_profile, {"payment_date": next_date})

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"charge_due_subscriptions failed: {exc}")
        raise
    logger.info("charge_due_subscriptions completed")


# ---------- Bot calls ----------


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def export_coach_payouts(self):
    logger.info("export_coach_payouts started")
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/export_coach_payouts/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        resp = httpx.post(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for coach payouts: {exc}")
        raise self.retry(exc=exc)
    logger.info("export_coach_payouts completed")


_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def send_daily_survey(self):
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/send_daily_survey/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        resp = httpx.post(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for daily survey: {exc!s}")
        raise self.retry(exc=exc)


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def send_workout_result(self, coach_profile_id: int, client_profile_id: int, text: str) -> None:
    """Forward workout survey results to the appropriate recipient."""
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/send_workout_result/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}
    payload = {
        "coach_id": coach_profile_id,
        "client_id": client_profile_id,
        "text": text,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=15.0, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for workout result: {exc!s}")
        raise self.retry(exc=exc)


# ---------- AI coach ----------


async def _claim_plan_request(request_id: str, action: str, *, attempt: int) -> bool:
    if not request_id or attempt > 0:
        return True
    try:
        client = get_redis_client()
        key = f"ai:plan:{action}:{request_id}"
        ok = await client.set(key, "1", nx=True, ex=settings.AI_PLAN_DEDUP_TTL)
        return bool(ok)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"ai_plan_idempotency_skip action={action} request_id={request_id} error={exc!s}")
        return True


class AIPlanNotificationError(Exception):
    def __init__(self, *, action: str, request_id: str, detail: str) -> None:
        self.action: str = action
        self.request_id: str = request_id
        self.detail: str = detail
        super().__init__(f"AI plan notification failed: {detail}")


async def _notify_ai_plan_ready(payload: dict[str, Any]) -> None:
    base_url: str = settings.BOT_INTERNAL_URL.rstrip("/")
    url: str = f"{base_url}/internal/tasks/ai_plan_ready/"
    headers: dict[str, str] = {"Authorization": f"Api-Key {settings.API_KEY}"}
    request_id = str(payload.get("request_id", ""))
    action = str(payload.get("action", ""))
    logger.info(f"ai_plan_notify_start action={action} request_id={request_id} url={url}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response: httpx.Response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code: int | None = exc.response.status_code if exc.response is not None else None
        detail: str = f"status={status_code} error={exc!s}"
        logger.error(f"ai_plan_notify_failed action={action} request_id={request_id} {detail}")
        raise AIPlanNotificationError(action=action, request_id=request_id, detail=detail) from exc
    except httpx.TransportError as exc:
        detail: str = f"transport_error={exc!r}"
        logger.error(f"ai_plan_notify_transport_error action={action} request_id={request_id} {detail}")
        raise AIPlanNotificationError(action=action, request_id=request_id, detail=detail) from exc
    logger.info(f"ai_plan_notify_done action={action} request_id={request_id} status={response.status_code}")


def _parse_workout_type(raw: Any) -> WorkoutType | None:
    if not raw:
        return None
    try:
        return WorkoutType(str(raw))
    except ValueError:
        return None


async def _notify_error(
    *,
    client_id: int,
    plan_type: WorkoutPlanType,
    request_id: str,
    action: str,
    error: str,
    client_profile_id: int | None,
) -> None:
    payload: dict[str, Any] = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "error",
        "action": action,
        "request_id": request_id,
        "error": error,
    }
    if client_profile_id is not None:
        payload["client_profile_id"] = client_profile_id
    await _notify_ai_plan_ready(payload)


async def _generate_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> None:
    client_id = int(payload["client_id"])
    client_profile_id_raw = payload.get("client_profile_id")
    client_profile_id: int | None
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else None
    except (TypeError, ValueError):
        logger.warning(
            f"ai_generate_plan invalid_profile_id client_id={client_id} "
            f"raw={client_profile_id_raw!r} request_id={payload.get('request_id', '')}"
        )
        client_profile_id = None
    request_id = str(payload.get("request_id", ""))
    wishes = str(payload.get("wishes", ""))
    language = str(payload.get("language", settings.DEFAULT_LANG))
    period = payload.get("period")
    workout_days = payload.get("workout_days") or []
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.PROGRAM.value))
    workout_type = _parse_workout_type(payload.get("workout_type"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "create", attempt=attempt):
        logger.info(
            f"ai_generate_plan_duplicate client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return

    logger.info(
        f"ai_generate_plan started client_id={client_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt}"
    )

    try:
        plan = await APIService.ai_coach.create_workout_plan(
            plan_type,
            client_id=client_id,
            language=language,
            period=str(period) if period else None,
            workout_days=list(workout_days),
            wishes=wishes,
            workout_type=workout_type,
            request_id=request_id or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_generate_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            try:
                await _notify_error(
                    client_id=client_id,
                    plan_type=plan_type,
                    request_id=request_id,
                    action="create",
                    error=str(exc),
                    client_profile_id=client_profile_id,
                )
            except AIPlanNotificationError as notify_exc:
                logger.error(
                    f"ai_generate_plan_error_notification_failed client_id={client_id} "
                    f"plan_type={plan_type.value} request_id={request_id} detail={notify_exc.detail}"
                )
        raise

    if plan is None:
        logger.error(
            f"ai_generate_plan returned empty client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        try:
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="create",
                error="empty_plan",
                client_profile_id=client_profile_id,
            )
        except AIPlanNotificationError as notify_exc:
            logger.error(
                f"ai_generate_plan_empty_notification_failed client_id={client_id} "
                f"plan_type={plan_type.value} request_id={request_id} detail={notify_exc.detail}"
            )
        return

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    notify_payload = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "create",
        "request_id": request_id,
        "plan": plan_payload,
    }
    if client_profile_id is not None:
        notify_payload["client_profile_id"] = client_profile_id

    try:
        await _notify_ai_plan_ready(notify_payload)
    except AIPlanNotificationError as exc:
        logger.error(
            f"ai_generate_plan_notification_failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} detail={exc.detail}"
        )
        raise
    logger.info(f"ai_generate_plan completed client_id={client_id} plan_type={plan_type.value} request_id={request_id}")


async def _update_ai_workout_plan_impl(payload: dict[str, Any], task: Task) -> None:
    client_id = int(payload["client_id"])
    client_profile_id_raw = payload.get("client_profile_id")
    client_profile_id: int | None
    try:
        client_profile_id = int(client_profile_id_raw) if client_profile_id_raw is not None else None
    except (TypeError, ValueError):
        logger.warning(
            f"ai_update_plan invalid_profile_id client_id={client_id} "
            f"raw={client_profile_id_raw!r} request_id={payload.get('request_id', '')}"
        )
        client_profile_id = None
    language = str(payload.get("language", settings.DEFAULT_LANG))
    request_id = str(payload.get("request_id", ""))
    expected_workout = str(payload.get("expected_workout_result", ""))
    feedback = str(payload.get("feedback", ""))
    plan_type = WorkoutPlanType(payload.get("plan_type", WorkoutPlanType.SUBSCRIPTION.value))
    workout_type = _parse_workout_type(payload.get("workout_type"))
    attempt = getattr(task.request, "retries", 0)

    if not await _claim_plan_request(request_id, "update", attempt=attempt):
        logger.info(
            f"ai_update_plan_duplicate client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        return

    logger.info(
        f"ai_update_plan started client_id={client_id} plan_type={plan_type.value} "
        f"request_id={request_id} attempt={attempt}"
    )

    try:
        plan = await APIService.ai_coach.update_workout_plan(
            plan_type,
            client_id=client_id,
            language=language,
            expected_workout=expected_workout or None,
            feedback=feedback or None,
            workout_type=workout_type,
            request_id=request_id or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"ai_update_plan failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} attempt={attempt} error={exc}"
        )
        if attempt >= getattr(task, "max_retries", 0):
            try:
                await _notify_error(
                    client_id=client_id,
                    plan_type=plan_type,
                    request_id=request_id,
                    action="update",
                    error=str(exc),
                    client_profile_id=client_profile_id,
                )
            except AIPlanNotificationError as notify_exc:
                logger.error(
                    f"ai_update_plan_error_notification_failed client_id={client_id} "
                    f"plan_type={plan_type.value} request_id={request_id} detail={notify_exc.detail}"
                )
        raise

    if plan is None:
        logger.error(
            f"ai_update_plan returned empty client_id={client_id} plan_type={plan_type.value} request_id={request_id}"
        )
        try:
            await _notify_error(
                client_id=client_id,
                plan_type=plan_type,
                request_id=request_id,
                action="update",
                error="empty_plan",
                client_profile_id=client_profile_id,
            )
        except AIPlanNotificationError as notify_exc:
            logger.error(
                f"ai_update_plan_empty_notification_failed client_id={client_id} "
                f"plan_type={plan_type.value} request_id={request_id} detail={notify_exc.detail}"
            )
        return

    if plan_type is WorkoutPlanType.PROGRAM:
        program = Program.model_validate(plan)
        plan_payload = program.model_dump(mode="json")
    else:
        subscription = Subscription.model_validate(plan)
        plan_payload = subscription.model_dump(mode="json")

    notify_payload = {
        "client_id": client_id,
        "plan_type": plan_type.value,
        "status": "success",
        "action": "update",
        "request_id": request_id,
        "plan": plan_payload,
    }
    if client_profile_id is not None:
        notify_payload["client_profile_id"] = client_profile_id

    try:
        await _notify_ai_plan_ready(notify_payload)
    except AIPlanNotificationError as exc:
        logger.error(
            f"ai_update_plan_notification_failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} detail={exc.detail}"
        )
        raise
    logger.info(f"ai_update_plan completed client_id={client_id} plan_type={plan_type.value} request_id={request_id}")


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientHTTPError, APIClientTransportError),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
)
def generate_ai_workout_plan(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    asyncio.run(_generate_ai_workout_plan_impl(payload, self))


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    autoretry_for=(APIClientHTTPError, APIClientTransportError),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
)
def update_ai_workout_plan(self, payload: dict[str, Any]) -> None:  # pyrefly: ignore[valid-type]
    asyncio.run(_update_ai_workout_plan_impl(payload, self))


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
)
def ai_coach_echo(self, payload: dict[str, Any]) -> dict[str, Any]:
    payload_descriptor: str
    if isinstance(payload, dict):
        payload_descriptor = ",".join(sorted(str(key) for key in payload.keys()))
    else:
        payload_descriptor = type(payload).__name__
    logger.info(f"ai_coach_echo started task_id={self.request.id} payload_descriptor={payload_descriptor}")
    return {"ok": True, "echo": payload}


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
)
def ai_coach_worker_report(self) -> dict[str, Any]:
    broker_url = str(getattr(app.conf, "broker_url", ""))
    backend_url = str(getattr(app.conf, "result_backend", ""))
    hostname = getattr(self.request, "hostname", None)
    logger.info(f"ai_coach_worker_report hostname={hostname} broker={broker_url} backend={backend_url}")
    queues = [queue.name for queue in getattr(app.conf, "task_queues", [])]
    return {
        "broker": broker_url,
        "backend": backend_url,
        "hostname": hostname,
        "queues": queues,
    }


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)
def refresh_external_knowledge(self):
    """Refresh external knowledge and rebuild Cognee index."""
    logger.info("refresh_external_knowledge triggered")

    async def _dedupe_window(window_s: int = 30) -> bool:
        r = get_redis_client()
        ok = await r.set("dedupe:refresh_external_knowledge", "1", nx=True, ex=window_s)
        return bool(ok)

    async def _impl() -> None:
        if not await _dedupe_window(30):
            logger.info("refresh_external_knowledge skipped: dedupe window active")
            return

        async with redis_try_lock(
            "locks:refresh_external_knowledge",
            ttl_ms=180_000,
            wait=False,
        ) as got:
            if not got:
                logger.info("refresh_external_knowledge skipped: lock is held")
                return

            for attempt in range(3):
                if await APIService.ai_coach.health(timeout=3.0):
                    break
                logger.warning(f"AI coach health check failed attempt {attempt + 1}")
                await asyncio.sleep(1)
            else:
                logger.warning("AI coach not ready, skipping refresh_external_knowledge")
                return
            await APIService.ai_coach.refresh_knowledge()

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"refresh_external_knowledge failed: {exc}")
        raise
    else:
        logger.info("refresh_external_knowledge completed")


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def prune_cognee(self):
    """Remove cached Cognee data storage."""
    logger.info("prune_cognee started")
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/prune_cognee/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        resp = httpx.post(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for prune_cognee: {exc}")
        raise self.retry(exc=exc)
    logger.info("prune_cognee completed")
