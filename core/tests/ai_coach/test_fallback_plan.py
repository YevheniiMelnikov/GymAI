from core.ai_coach_fallback import FALLBACK_WORKOUT_DAYS, fallback_plan
from core.enums import CoachType, WorkoutPlanType


def test_fallback_program_structure() -> None:
    plan = fallback_plan(
        plan_type=WorkoutPlanType.PROGRAM,
        client_profile_id=7,
        workout_type="strength",
        wishes="test",
        workout_days=["Mon", "Wed"],
        period=None,
    )
    assert plan.client_profile == 7
    assert len(plan.exercises_by_day) == 2
    assert plan.split_number == 2
    assert plan.coach_type is CoachType.ai_coach
    assert plan.workout_type == "strength"
    assert plan.wishes == "test"
    assert all(day.exercises for day in plan.exercises_by_day)
    assert plan.created_at > 0


def test_fallback_subscription_defaults() -> None:
    subscription = fallback_plan(
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        client_profile_id=5,
        workout_type=None,
        wishes=None,
        workout_days=[],
        period="one_month",
    )
    assert subscription.client_profile == 5
    assert subscription.workout_days == list(FALLBACK_WORKOUT_DAYS)
    assert subscription.workout_type == "general"
    assert subscription.wishes == ""
    assert subscription.period == "one_month"
    assert subscription.exercises
