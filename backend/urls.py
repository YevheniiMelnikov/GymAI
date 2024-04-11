from accounts import views
from django.contrib import admin
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework.routers import SimpleRouter

api_info = openapi.Info(title="Admin Rest", default_version="0.1")
schema_view = get_schema_view(api_info, public=True, url="", permission_classes=[permissions.IsAuthenticated])
router = SimpleRouter()
router.register(r"persons", views.PersonViewSet, basename="persons")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger"),
    path("api/v1/", include(router.urls)),
    # path("api/v1/", include("accounts.urls")),
]
