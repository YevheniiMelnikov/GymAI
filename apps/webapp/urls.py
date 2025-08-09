from django.urls import path, re_path
from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),
    path("", views.index, name="webapp"),
    re_path(r"^(?!api/).*$", views.index),
]
