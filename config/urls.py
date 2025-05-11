from django.urls import include, path

from apps.payments.views import PaymentWebhookView


urlpatterns = [
    path("payment-webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("api/v1/", include("apps.profiles.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.workout_plans.urls")),
    path("", include("apps.home.urls")),
]
