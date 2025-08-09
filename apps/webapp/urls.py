from django.urls import path, re_path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("api/program/", views.program_data, name="webapp-program-data"),
    re_path(
        r"^(?!api/)(?:.*)/?$",
        TemplateView.as_view(template_name="webapp/index.html"),
    ),
]
