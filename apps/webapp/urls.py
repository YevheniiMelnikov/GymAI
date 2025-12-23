from django.urls import path, re_path

from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),  # pyrefly: ignore[no-matching-overload]
    path(  # pyrefly: ignore[no-matching-overload]
        "api/programs/", views.programs_history, name="webapp-programs-history"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/subscription/", views.subscription_data, name="webapp-subscription-data"
    ),
    path("api/payment/", views.payment_data, name="webapp-payment-data"),  # pyrefly: ignore[no-matching-overload]
    path(  # pyrefly: ignore[no-matching-overload]
        "api/workouts/action/", views.workouts_action, name="webapp-workouts-action"
    ),
    path(  # pyrefly: ignore[no-matching-overload]
        "api/program/exercise/", views.update_exercise_sets, name="webapp-program-exercise-update"
    ),
    path("", views.index, name="webapp"),
    path("__ping__", views.ping, name="webapp-ping"),
    re_path(r"^(?!api/).*$", views.index),
]
