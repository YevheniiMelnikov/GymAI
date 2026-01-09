from typing import Callable, cast

from django.http import JsonResponse, HttpResponseNotFound, HttpResponseBase
from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView
from loguru import logger

from apps.payments.views import PaymentWebhookView
from apps.webapp import views as webapp_views
from apps.metrics import views as metrics_views


WebappView = Callable[..., HttpResponseBase]


def healthcheck_view(_):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", healthcheck_view, name="healthcheck"),
    path("payments-webhook/", PaymentWebhookView.as_view(), name="payments-webhook"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.profiles.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.workout_plans.urls")),
    path("api/program/", webapp_views.program_data, name="webapp-program-data-direct"),  # type: ignore[arg-type]
    path("api/programs/", webapp_views.programs_history, name="webapp-programs-history-direct"),  # type: ignore[arg-type]
    path("api/subscription/", webapp_views.subscription_data, name="webapp-subscription-data-direct"),  # type: ignore[arg-type]
    path(
        "api/subscription/status/",
        cast(WebappView, webapp_views.subscription_status),
        name="webapp-subscription-status-direct",
    ),
    path("api/payment/init/", webapp_views.payment_init, name="webapp-payment-init-direct"),  # type: ignore[arg-type]
    path("api/payment/", webapp_views.payment_data, name="webapp-payment-data-direct"),  # type: ignore[arg-type]
    path("api/profile/", webapp_views.profile_data, name="webapp-profile-data-direct"),  # type: ignore[arg-type]
    path(
        "api/profile/update/",
        cast(WebappView, webapp_views.profile_update),
        name="webapp-profile-update-direct",
    ),
    path(
        "api/profile/delete/",
        cast(WebappView, webapp_views.profile_delete),
        name="webapp-profile-delete-direct",
    ),
    path(
        "api/profile/balance/",
        cast(WebappView, webapp_views.profile_balance_action),
        name="webapp-profile-balance-direct",
    ),
    path(
        "api/support/",
        cast(WebappView, webapp_views.support_contact),
        name="webapp-support-contact-direct",
    ),
    path("api/workouts/action/", webapp_views.workouts_action, name="webapp-workouts-action-direct"),  # type: ignore[arg-type]
    path(
        "api/workouts/options/",
        cast(WebappView, webapp_views.workout_plan_options),
        name="webapp-workouts-options-direct",
    ),
    path(
        "api/workouts/create/",
        cast(WebappView, webapp_views.workout_plan_create),
        name="webapp-workouts-create-direct",
    ),
    path("api/diets/", webapp_views.diet_plans_list, name="webapp-diets-direct"),  # type: ignore[arg-type]
    path("api/diet/", webapp_views.diet_plan_data, name="webapp-diet-direct"),  # type: ignore[arg-type]
    path(
        "api/diets/options/",
        cast(WebappView, webapp_views.diet_plan_options),
        name="webapp-diets-options-direct",
    ),
    path(
        "api/diets/create/",
        cast(WebappView, webapp_views.diet_plan_create),
        name="webapp-diets-create-direct",
    ),
    path(
        "api/weekly-survey/",
        cast(WebappView, webapp_views.weekly_survey_submit),
        name="webapp-weekly-survey-submit-direct",
    ),
    path(
        "internal/metrics/event/",
        cast(WebappView, metrics_views.record_metrics_event),
        name="internal-metrics-event",
    ),
    path(
        "internal/diets/",
        cast(WebappView, webapp_views.diet_plan_save_internal),
        name="internal-diet-plan-save",
    ),
    path(
        "api/program/exercise/",
        cast(WebappView, webapp_views.update_exercise_sets),
        name="webapp-program-exercise-update-direct",
    ),
    path(
        "api/subscription/exercise/",
        cast(WebappView, webapp_views.update_subscription_exercise_sets),
        name="webapp-subscription-exercise-update-direct",
    ),
    path(
        "api/program/exercise/replace/",
        cast(WebappView, webapp_views.replace_exercise),
        name="webapp-program-exercise-replace-direct",
    ),
    path(
        "api/subscription/exercise/replace/",
        cast(WebappView, webapp_views.replace_subscription_exercise),
        name="webapp-subscription-exercise-replace-direct",
    ),
    path(
        "api/program/exercise/replace/status/",
        cast(WebappView, webapp_views.replace_exercise_status),
        name="webapp-program-exercise-replace-status-direct",
    ),
    path(
        "api/subscription/exercise/replace/status/",
        cast(WebappView, webapp_views.replace_subscription_exercise_status),
        name="webapp-subscription-exercise-replace-status-direct",
    ),
    path(
        "api/gif/<path:gif_key>/",
        cast(WebappView, webapp_views.exercise_gif),
        name="webapp-exercise-gif-direct",
    ),
    path(
        "api/generation-status/",
        cast(WebappView, webapp_views.generation_status),
        name="webapp-generation-status-direct",
    ),
    path("webapp", RedirectView.as_view(url="/webapp/", permanent=False)),
    path("webapp/", include("apps.webapp.urls")),
    path("", RedirectView.as_view(url="/webapp/", permanent=False, query_string=True)),
]


def not_found_view(request, exception):
    logger.warning(f"Unhandled path 404: {request.get_full_path()}")
    return HttpResponseNotFound()


handler404 = not_found_view
