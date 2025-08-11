from django.urls import path, re_path
from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),
    path("api/subscription/", views.subscription_data, name="webapp-subscription-data"),
    path("", views.index, name="webapp"),
    path("__ping__", views.ping, name="webapp-ping"),
    re_path(r"^(?!api/).*$", views.index),
]
