from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot
from loguru import logger

from bot.keyboards import workout_survey_kb
from bot.texts.text_manager import msg_text
from bot.utils.profiles import get_clients_to_survey
from config.app_settings import settings
from ai_coach.utils.parsers import parse_program_text, parse_program_json
from core.exceptions import SubscriptionNotFoundError
from core.payment_processor import PaymentProcessor
from core.cache import Cache
from core.enums import CoachType
from bot.utils.chat import send_message
from aiogram.enums import ParseMode
from core.services import APIService
from bot.utils.ai_services import process_workout_result
from cognee.api.v1.prune import prune


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
        await PaymentProcessor.export_coach_payouts()
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

    if not coach_id or not client_id or client_workout_feedback is None:
        return web.json_response({"detail": "Missing parameters"}, status=400)

    bot: Bot = request.app["bot"]
    coach = await Cache.coach.get_coach(int(coach_id))
    if not coach:
        return web.json_response({"detail": "Coach not found"}, status=404)

    if coach.coach_type == CoachType.ai:
        await APIService.ai_coach.save_user_message(
            str(client_workout_feedback), chat_id=int(client_id), client_id=int(client_id)
        )
        client = await Cache.client.get_client(int(client_id))
        profile = await APIService.profile.get_profile(client.profile)
        updated_workout = await process_workout_result(
            client_id=int(client_id),
            expected_workout_result=expected_workout_result,
            feedback=str(client_workout_feedback),
            language=profile.language if profile else settings.DEFAULT_LANG,
        )
        if profile is not None and updated_workout:
            dto = parse_program_json(updated_workout)
            if dto is not None:
                exercises = dto.days
            else:
                exercises, _ = parse_program_text(updated_workout)

            if not exercises:
                logger.error("AI workout update produced no exercises")
                return web.json_response({"result": "AI workout update produced no exercises"})

            try:
                subscription = await Cache.workout.get_latest_subscription(client_id)
            except SubscriptionNotFoundError:
                logger.error(f"No subscription found for client_id={client_id}")
                return web.json_response({"result": f"No subscription found for client_id={client_id}"})

            serialized = [day.model_dump() for day in exercises]
            subscription_data = subscription.model_dump()
            subscription_data.update(client_profile=client_id, exercises=serialized)

            await APIService.workout.update_subscription(subscription.id, subscription_data)
            await Cache.workout.update_subscription(
                client_id,
                {"exercises": serialized, "client_profile": client_id},
            )
            await bot.send_message(
                chat_id=profile.tg_id,
                text=msg_text("program_updated", profile.language),
                parse_mode=ParseMode.HTML,
            )
    else:
        await send_message(
            recipient=coach,
            text=str(client_workout_feedback),
            bot=bot,
            state=None,
            include_incoming_message=False,
        )

    return web.json_response({"result": "ok"})


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
