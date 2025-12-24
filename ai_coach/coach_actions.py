from typing import Awaitable, Callable, cast

from ai_coach.agent import CoachAgent
from ai_coach.types import AskCtx, CoachMode
from core.enums import WorkoutPlanType
from core.schemas import DietPlan, Program, QAResponse, Subscription

CoachAction = Callable[[AskCtx], Awaitable[Program | Subscription | QAResponse | DietPlan | list[str] | None]]


def _dispatch_program(ctx: AskCtx) -> Awaitable[Program | None]:
    workout_days = ctx.get("workout_days")
    if workout_days is None:
        return cast(
            Awaitable[Program],
            CoachAgent.generate_workout_plan(
                ctx.get("prompt"),
                deps=ctx["deps"],
                workout_location=ctx.get("workout_location"),
                wishes=ctx["wishes"],
                profile_context=ctx.get("profile_context"),
                instructions=ctx.get("instructions"),
                output_type=Program,
            ),
        )
    return cast(
        Awaitable[Program],
        CoachAgent.generate_workout_plan(
            ctx.get("prompt"),
            deps=ctx["deps"],
            workout_location=ctx.get("workout_location"),
            workout_days=workout_days,
            wishes=ctx["wishes"],
            profile_context=ctx.get("profile_context"),
            instructions=ctx.get("instructions"),
            output_type=Program,
        ),
    )


DISPATCH: dict[CoachMode, CoachAction] = {
    CoachMode.program: _dispatch_program,
    CoachMode.subscription: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_location=ctx.get("workout_location"),
        period=ctx["period"],
        workout_days=ctx["workout_days"],
        wishes=ctx["wishes"],
        profile_context=ctx.get("profile_context"),
        instructions=ctx.get("instructions"),
        output_type=Subscription,
    ),
    CoachMode.update: lambda ctx: CoachAgent.update_workout_plan(
        ctx.get("prompt"),
        expected_workout=ctx["expected_workout"],
        feedback=ctx["feedback"],
        workout_location=ctx.get("workout_location"),
        deps=ctx["deps"],
        output_type=Program if ctx["plan_type"] == WorkoutPlanType.PROGRAM else Subscription,
        profile_context=ctx.get("profile_context"),
        instructions=ctx.get("instructions"),
    ),
    CoachMode.ask_ai: lambda ctx: CoachAgent.answer_question(
        ctx["prompt"] or "",
        deps=ctx["deps"],
        **({"attachments": ctx["attachments"]} if ctx.get("attachments") else {}),
    ),
    CoachMode.diet: lambda ctx: CoachAgent.generate_diet_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        profile_context=ctx.get("profile_context"),
        diet_allergies=ctx.get("diet_allergies"),
        diet_products=ctx.get("diet_products"),
        instructions=ctx.get("instructions"),
    ),
}
