from django.http import JsonResponse, HttpResponseNotFound
from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView
from loguru import logger

from apps.payments.views import PaymentWebhookView
from apps.webapp import views as webapp_views


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
    path("api/payment/", webapp_views.payment_data, name="webapp-payment-data-direct"),  # type: ignore[arg-type]
    path("webapp", RedirectView.as_view(url="/webapp/", permanent=False)),
    path("webapp/", include("apps.webapp.urls")),
    path("", RedirectView.as_view(url="/webapp/", permanent=False, query_string=True)),
]


def not_found_view(request, exception):
    logger.warning(f"Unhandled path 404: {request.get_full_path()}")
    return HttpResponseNotFound()


handler404 = not_found_view
