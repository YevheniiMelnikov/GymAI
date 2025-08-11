from django.urls import path, re_path
from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),
    path("", views.index, name="webapp"),
    path("test/", views.test, name="webapp-test"),
    path("__ping__", views.ping, name="webapp-ping"),
    re_path(r"^(?!api/).*$", views.index),
]
