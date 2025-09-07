from django.http import JsonResponse, HttpResponseNotFound
from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView
from loguru import logger

from apps.payments.views import PaymentWebhookView


def healthcheck_view(_):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", healthcheck_view, name="healthcheck"),
    path("payments-webhook/", PaymentWebhookView.as_view(), name="payments-webhook"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.profiles.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.workout_plans.urls")),
    path("webapp", RedirectView.as_view(url="/webapp/", permanent=False)),
    path("webapp/", include("apps.webapp.urls")),
    path(
        "",
        RedirectView.as_view(url="/webapp/", permanent=False, query_string=True),
    ),
]


def not_found_view(request, exception):
    logger.warning(f"Unhandled path 404: {request.get_full_path()}")
    return HttpResponseNotFound()


handler404 = not_found_view
