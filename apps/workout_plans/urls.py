from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.workout_plans.views import ProgramViewSet, SubscriptionViewSet

program_router = DefaultRouter()
program_router.register(r"programs", ProgramViewSet)

subscription_router = DefaultRouter()
subscription_router.register(r"subscriptions", SubscriptionViewSet)

urlpatterns = [
    path("", include(program_router.urls)),
    path("", include(subscription_router.urls)),
]
