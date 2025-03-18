from django.contrib import admin
from django.urls import include, path
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions

from api.payments.views import PaymentWebhookView

api_info = openapi.Info(title="GymBot API", default_version="0.1")
schema_view = get_schema_view(api_info, public=True, url="", permission_classes=[permissions.IsAuthenticated])

urlpatterns = [
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger"),
    path("admin/", admin.site.urls),
    path("payment-webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("api/v1/drf-auth/", include("rest_framework.urls")),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("payments.urls")),
    path("", include("home.urls")),
]
