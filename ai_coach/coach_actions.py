from typing import Awaitable, Callable

from ai_coach.agent import CoachAgent
from ai_coach.types import AskCtx, CoachMode
from core.enums import WorkoutPlanType
from core.schemas import Program, QAResponse, Subscription

CoachAction = Callable[[AskCtx], Awaitable[Program | Subscription | QAResponse | list[str] | None]]

DISPATCH: dict[CoachMode, CoachAction] = {
    CoachMode.program: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_location=ctx.get("workout_location"),
        wishes=ctx["wishes"],
        instructions=ctx.get("instructions"),
        output_type=Program,
    ),
    CoachMode.subscription: lambda ctx: CoachAgent.generate_workout_plan(
        ctx.get("prompt"),
        deps=ctx["deps"],
        workout_location=ctx.get("workout_location"),
        period=ctx["period"],
        workout_days=ctx["workout_days"],
        wishes=ctx["wishes"],
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
        instructions=ctx.get("instructions"),
    ),
    CoachMode.ask_ai: lambda ctx: CoachAgent.answer_question(
        ctx["prompt"] or "",
        deps=ctx["deps"],
        **({"attachments": ctx["attachments"]} if ctx.get("attachments") else {}),
    ),
}
