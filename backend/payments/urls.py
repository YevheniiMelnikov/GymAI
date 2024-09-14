from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProgramViewSet,
    SubscriptionViewSet,
    PaymentCreateView,
    PaymentListView,
    PaymentDetailView,
    PaymentWebhookView,
)

program_router = DefaultRouter()
program_router.register(r"programs", ProgramViewSet)

subscription_router = DefaultRouter()
subscription_router.register(r"subscriptions", SubscriptionViewSet)

urlpatterns = [
    path("", include(program_router.urls)),
    path("", include(subscription_router.urls)),
    path("payments/create/", PaymentCreateView.as_view(), name="payments-create"),
    path("payments/", PaymentListView.as_view(), name="payments-list"),
    path("payments/<int:pk>/", PaymentDetailView.as_view(), name="payment-update"),
    path("payment-webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
]
