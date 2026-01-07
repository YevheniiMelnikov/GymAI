from typing import Any, Callable, Coroutine, cast
from django.urls import path, re_path
from django.http import HttpResponseBase

from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),  # pyrefly: ignore[no-matching-overload]
    path(  # pyrefly: ignore[no-matching-overload]
        "api/programs/", views.programs_history, name="webapp-programs-history"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/", views.subscription_data, name="webapp-subscription-data"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/status/", views.subscription_status, name="webapp-subscription-status"
    ),
    path("api/payment/init/", views.payment_init, name="webapp-payment-init"),  # pyrefly: ignore[no-matching-overload]
    path("api/payment/", views.payment_data, name="webapp-payment-data"),  # pyrefly: ignore[no-matching-overload]
    path("api/profile/", views.profile_data, name="webapp-profile-data"),  # pyrefly: ignore[no-matching-overload]
    path(  # pyrefly: ignore[no-matching-overload]
        "api/profile/update/",
        views.profile_update,
        name="webapp-profile-update",
    ),
    path("api/diets/", views.diet_plans_list, name="webapp-diet-plans"),  # pyrefly: ignore[no-matching-overload]
    path("api/diet/", views.diet_plan_data, name="webapp-diet-plan"),  # pyrefly: ignore[no-matching-overload]
    path(
        "api/diets/options/",
        cast(Callable[..., Coroutine[Any, Any, HttpResponseBase]], views.diet_plan_options),
        name="webapp-diet-options",
    ),
    path(
        "api/diets/create/",
        cast(Callable[..., Coroutine[Any, Any, HttpResponseBase]], views.diet_plan_create),
        name="webapp-diet-create",
    ),  # pyrefly: ignore[no-matching-overload]
    path(  # pyrefly: ignore[no-matching-overload]
        "api/profile/delete/",
        views.profile_delete,
        name="webapp-profile-delete",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/profile/balance/",
        views.profile_balance_action,
        name="webapp-profile-balance",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/support/",
        views.support_contact,
        name="webapp-support-contact",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/workouts/action/", views.workouts_action, name="webapp-workouts-action"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/workouts/options/",
        views.workout_plan_options,
        name="webapp-workouts-options",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/workouts/create/",
        views.workout_plan_create,
        name="webapp-workouts-create",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/weekly-survey/",
        views.weekly_survey_submit,
        name="webapp-weekly-survey-submit",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/program/exercise/replace/",
        views.replace_exercise,
        name="webapp-program-exercise-replace",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/exercise/replace/",
        views.replace_subscription_exercise,
        name="webapp-subscription-exercise-replace",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/program/exercise/replace/status/",
        views.replace_exercise_status,
        name="webapp-program-exercise-replace-status",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/exercise/replace/status/",
        views.replace_subscription_exercise_status,
        name="webapp-subscription-exercise-replace-status",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/program/exercise/", views.update_exercise_sets, name="webapp-program-exercise-update"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/exercise/",
        views.update_subscription_exercise_sets,
        name="webapp-subscription-exercise-update",
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/gif/<path:gif_key>/",
        views.exercise_gif,
        name="webapp-exercise-gif",
    ),
    path("", views.index, name="webapp"),
    path("__ping__", views.ping, name="webapp-ping"),
    re_path(r"^(?!api/).*$", views.index),
]
