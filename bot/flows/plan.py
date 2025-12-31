from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, cast
from uuid import uuid4

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from loguru import logger

from bot.keyboards import confirm_service_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.ai_coach import enqueue_workout_plan_generation
from bot.utils.bot import answer_msg, del_msg, notify_request_in_progress
from bot.utils.menus import ensure_credits, reset_main_menu_state
from bot.utils.profiles import resolve_workout_location
from config.app_settings import settings
from core.cache import Cache
from core.enums import SubscriptionPeriod, WorkoutLocation, WorkoutPlanType
from bot.services.pricing import ServiceCatalog
from core.exceptions import SubscriptionNotFoundError
from core.schemas import Profile, Subscription
from core.services import APIService
from core.utils.idempotency import acquire_once


@dataclass(slots=True)
class PlanFlowContext:
    """Shared state for plan generation flows."""

    callback_query: CallbackQuery
    profile: Profile
    state: FSMContext
    language: str
    data: Mapping[str, object]
    profile_record: Profile
    split_number: int
    required: int
    workout_location: WorkoutLocation | None = None
    period: SubscriptionPeriod | None = None


class PlanFlowBase(ABC):
    """Template for credit-paid plan generation flows."""

    def __init__(self, callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
        self._callback_query = callback_query
        self._profile = profile
        self._state = state

    async def run(self, *, confirmed: bool) -> None:
        language: str = self._profile.language or settings.DEFAULT_LANG
        data = await self._state.get_data()
        profile_record = await Cache.profile.get_record(self._profile.id)
        raw_split = data.get("split_number", 3)
        try:
            split_number = int(raw_split)
        except (TypeError, ValueError):
            split_number = 3
        split_number = max(1, min(7, split_number))
        required = int(data.get("required", 0))
        context = PlanFlowContext(
            callback_query=self._callback_query,
            profile=self._profile,
            state=self._state,
            language=language,
            data=data,
            profile_record=profile_record,
            split_number=split_number,
            required=required,
        )
        if not await ensure_credits(
            self._callback_query,
            self._profile,
            self._state,
            required=required,
            credits=profile_record.credits,
        ):
            return

        if not await self._pre_check(context):
            return

        if not confirmed:
            await self._prepare_confirmation(context)
            return

        if not await acquire_once(self._acquire_key(context), settings.LLM_COOLDOWN):
            logger.warning(f"Duplicate {self._plan_label()} generation suppressed for profile_id={profile_record.id}")
            await del_msg(self._callback_query)
            return

        await self._execute(context)

    @abstractmethod
    async def _pre_check(self, context: PlanFlowContext) -> bool:
        return True

    @abstractmethod
    def _plan_label(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _acquire_key(self, context: PlanFlowContext) -> str:
        raise NotImplementedError

    @abstractmethod
    async def _execute(self, context: PlanFlowContext) -> None:
        raise NotImplementedError

    async def _prepare_confirmation(self, context: PlanFlowContext) -> None:
        await self._update_confirmation_state(context)
        await context.state.set_state(States.confirm_service)
        await answer_msg(
            context.callback_query,
            translate(MessageText.confirm_service, context.language).format(
                balance=context.profile_record.credits,
                price=context.required,
            ),
            reply_markup=confirm_service_kb(context.language),
        )

    async def _update_confirmation_state(self, context: PlanFlowContext) -> None:
        await context.state.update_data(required=context.required)


class SubscriptionPlanFlow(PlanFlowBase):
    """Subscription-specific flow implementation."""

    async def _pre_check(self, context: PlanFlowContext) -> bool:
        if context.required <= 0:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            logger.error(
                f"subscription_required_missing profile_id={context.profile_record.id} required={context.required}"
            )
            return False
        if not context.data.get("service_type"):
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            logger.error(f"subscription_service_missing profile_id={context.profile_record.id}")
            return False
        if context.split_number <= 0:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            logger.error(
                f"subscription_split_missing profile_id={context.profile_record.id} split_number={context.split_number}"
            )
            return False
        workout_location = context.data.get("split_number_location")
        if workout_location is None:
            workout_location = resolve_workout_location(context.profile_record)
        if workout_location is None:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            return False
        context.workout_location = (
            workout_location
            if isinstance(workout_location, WorkoutLocation)
            else WorkoutLocation(str(workout_location))
        )
        context.period = self._resolve_period(context.data)
        existing = await self._get_latest_subscription(context.profile_record.id)
        if existing and existing.enabled:
            existing_id = getattr(existing, "id", None)
            if existing_id:
                await context.state.update_data(previous_subscription_id=existing_id)
        return True

    def _plan_label(self) -> str:
        return "subscription"

    def _acquire_key(self, context: PlanFlowContext) -> str:
        return f"gen_subscription:{context.profile_record.id}"

    async def _update_confirmation_state(self, context: PlanFlowContext) -> None:
        period = context.period or SubscriptionPeriod.one_month
        await context.state.update_data(required=context.required, period=period.value)

    async def _execute(self, context: PlanFlowContext) -> None:
        period = context.period or SubscriptionPeriod.one_month
        workout_location = context.workout_location
        if workout_location is None:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            return
        sub_id = await APIService.workout.create_subscription(
            profile_id=context.profile_record.id,
            split_number=context.split_number,
            wishes=str(context.data.get("wishes", "")),
            amount=Decimal(context.required),
            period=period,
            workout_location=workout_location.value,
        )
        if sub_id is None:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            return

        await APIService.profile.adjust_credits(context.profile.id, -context.required)
        await Cache.profile.update_record(
            context.profile_record.id,
            {"credits": context.profile_record.credits - context.required},
        )
        await Cache.workout.update_subscription(
            context.profile_record.id,
            {
                "id": sub_id,
                "enabled": False,
                "period": period.value,
                "price": context.required,
                "workout_location": workout_location.value,
                "wishes": str(context.data.get("wishes", "")),
                "split_number": context.split_number,
            },
        )
        await context.state.update_data(subscription_id=sub_id)
        request_id = uuid4().hex
        await notify_request_in_progress(context.callback_query, context.language)
        await reset_main_menu_state(context.state, context.profile)
        await del_msg(context.callback_query)
        queued = await enqueue_workout_plan_generation(
            profile=context.profile_record,
            plan_type=WorkoutPlanType.SUBSCRIPTION,
            workout_location=workout_location,
            wishes=str(context.data.get("wishes", "")),
            request_id=request_id,
            period=period.value,
            split_number=context.split_number,
            previous_subscription_id=cast(int | None, context.data.get("previous_subscription_id")),
        )
        if not queued:
            await answer_msg(
                context.callback_query,
                translate(MessageText.coach_agent_error, context.language).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            logger.error(
                f"ai_plan_dispatch_failed plan_type=subscription profile_id={context.profile_record.id} "
                f"request_id={request_id}"
            )
            return
        logger.debug(
            "AI coach plan generation started plan_type=subscription "
            f"profile_id={context.profile_record.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
        )
        logger.info(
            f"ai_plan_generation_requested request_id={request_id} profile_id={context.profile_record.id} "
            f"plan_type={WorkoutPlanType.SUBSCRIPTION.value}"
        )
        await del_msg(context.callback_query)

    @staticmethod
    async def _get_latest_subscription(profile_id: int) -> Subscription | None:
        try:
            return await Cache.workout.get_latest_subscription(profile_id)
        except SubscriptionNotFoundError:
            return None

    @staticmethod
    def _resolve_period(data: Mapping[str, object]) -> SubscriptionPeriod:
        service_type = str(data.get("service_type", "subscription"))
        period_value = data.get("split_number_period")
        if period_value:
            try:
                return SubscriptionPeriod(str(period_value))
            except ValueError:
                return (
                    ServiceCatalog.subscription_period(str(data.get("ai_service") or service_type))
                    or SubscriptionPeriod.one_month
                )
        return (
            ServiceCatalog.subscription_period(str(data.get("ai_service") or service_type))
            or SubscriptionPeriod.one_month
        )


class ProgramPlanFlow(PlanFlowBase):
    """Program-specific flow implementation."""

    async def _pre_check(self, context: PlanFlowContext) -> bool:
        if context.required <= 0:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            logger.error(f"program_required_missing profile_id={context.profile_record.id} required={context.required}")
            return False
        if context.split_number <= 0:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            logger.error(
                f"program_split_missing profile_id={context.profile_record.id} split_number={context.split_number}"
            )
            return False
        workout_location_value = context.data.get("split_number_location")
        if not workout_location_value:
            logger.error(f"Workout location missing during program flow for profile_id={context.profile.id}")
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            return False
        context.workout_location = (
            workout_location_value
            if isinstance(workout_location_value, WorkoutLocation)
            else WorkoutLocation(str(workout_location_value))
        )
        return True

    def _plan_label(self) -> str:
        return "program"

    def _acquire_key(self, context: PlanFlowContext) -> str:
        return f"gen_program:{context.profile_record.id}"

    async def _execute(self, context: PlanFlowContext) -> None:
        workout_location = context.workout_location
        if workout_location is None:
            await context.callback_query.answer(
                translate(MessageText.unexpected_error, context.language), show_alert=True
            )
            return

        await APIService.profile.adjust_credits(context.profile.id, -context.required)
        await Cache.profile.update_record(
            context.profile.id,
            {"credits": context.profile_record.credits - context.required},
        )
        request_id = uuid4().hex
        await notify_request_in_progress(context.callback_query, context.language)
        await reset_main_menu_state(context.state, context.profile)
        await del_msg(context.callback_query)
        queued = await enqueue_workout_plan_generation(
            profile=context.profile_record,
            plan_type=WorkoutPlanType.PROGRAM,
            workout_location=workout_location,
            wishes=str(context.data.get("wishes", "")),
            request_id=request_id,
            split_number=context.split_number,
        )
        if not queued:
            await answer_msg(
                context.callback_query,
                translate(MessageText.coach_agent_error, context.language).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            logger.error(
                f"ai_plan_dispatch_failed plan_type=program profile_id={context.profile_record.id} "
                f"request_id={request_id}"
            )
            return
        logger.debug(
            "AI coach plan generation started plan_type=program "
            f"profile_id={context.profile_record.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
        )
        logger.info(
            f"ai_plan_generation_requested request_id={request_id} profile_id={context.profile_record.id} "
            f"plan_type={WorkoutPlanType.PROGRAM.value}"
        )
        await del_msg(context.callback_query)
