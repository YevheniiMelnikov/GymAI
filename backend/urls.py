from accounts.views import CreateUserView, ProfileAPIDestroy, ProfileAPIList, ProfileAPIUpdate
from django.contrib import admin
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

api_info = openapi.Info(title="Admin Rest", default_version="0.1")
schema_view = get_schema_view(api_info, public=True, url="", permission_classes=[permissions.IsAuthenticated])

urlpatterns = [
    path("admin/", admin.site.urls),
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger"),
    path("api/v1/drf-auth/", include("rest_framework.urls")),
    path("api/v1/auth/", include("djoser.urls")),
    re_path(r"^auth/", include("djoser.urls.authtoken")),
    path("api/v1/persons/", ProfileAPIList.as_view(), name="person_list"),
    path("api/v1/persons/<int:pk>/", ProfileAPIUpdate.as_view(), name="person-update"),
    path("api/v1/persons/<int:pk>/delete/", ProfileAPIDestroy.as_view(), name="person-delete"),
    path("api/v1/persons/create/", CreateUserView.as_view(), name="person-create"),
]
