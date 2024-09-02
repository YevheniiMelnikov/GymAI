from accounts.views import *
from django.contrib import admin
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework.routers import DefaultRouter

api_info = openapi.Info(title="Admin Rest", default_version="0.1")
schema_view = get_schema_view(api_info, public=True, url="", permission_classes=[permissions.IsAuthenticated])
program_router = DefaultRouter()
program_router.register(r"programs", ProgramViewSet)
subscription_router = DefaultRouter()
subscription_router.register(r"subscriptions", SubscriptionViewSet)

urlpatterns = [
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger"),
    path("api/v1/drf-auth/", include("rest_framework.urls")),
    path("api/v1/auth/", include("djoser.urls")),
    re_path(r"^auth/", include("djoser.urls.authtoken")),
    path("api/v1/persons/", ProfileAPIList.as_view(), name="profile_list"),
    path("api/v1/persons/<int:profile_id>/", ProfileAPIUpdate.as_view(), name="profile-update"),
    path("api/v1/persons/reset-tg/<int:profile_id>/", ResetTelegramIDView.as_view(), name="reset-tg"),
    path("api/v1/persons/tg/<int:telegram_id>/", ProfileByTelegramIDView.as_view(), name="profile-by-tg-id"),
    path("api/v1/persons/<int:id>/delete/", ProfileAPIDestroy.as_view(), name="profile-delete"),
    path("api/v1/persons/create/", CreateUserView.as_view(), name="profile-create"),
    path("api/v1/persons/<str:username>/", UserProfileView.as_view(), name="user-profile"),
    path("api/v1/persons/tg/<int:telegram_id>/", ProfileByTelegramIDView.as_view(), name="profile-by-tg-id"),
    path("password-reset/<uidb64>/<token>/", reset_password_request_view, name="password-reset-confirm"),
    path("api/v1/current-user/", CurrentUserView.as_view(), name="current-user"),
    path("api/v1/send-feedback/", SendFeedbackAPIView.as_view(), name="send-feedback"),
    path("api/v1/", include(program_router.urls)),
    path("api/v1/", include(subscription_router.urls)),
    path("api/v1/get-user-token/", GetUserTokenView.as_view(), name="get-user-token"),
    path("api/v1/send-welcome-email/", SendWelcomeEmailAPIView.as_view(), name="send_welcome_email"),
    path("api/v1/payments/create/", PaymentCreateView.as_view(), name="payments-create"),
    path("api/v1/payments/", PaymentListView.as_view(), name="payments-list"),
    path("api/v1/payments/<int:pk>/", PaymentDetailView.as_view(), name="payment-update"),
    path("payment-webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
]
