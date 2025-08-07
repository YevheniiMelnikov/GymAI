from django.urls import path
from . import views

urlpatterns = [
    path("program/", views.program_page, name="webapp-program"),
    path("api/program/", views.program_data, name="webapp-program-data"),
]
