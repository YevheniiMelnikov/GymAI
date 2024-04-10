"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from accounts import views
from django.contrib import admin
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework.routers import DefaultRouter

api_info = openapi.Info(title="Admin Rest", default_version="0.1")
schema_view = get_schema_view(api_info, public=True, url="", permission_classes=[permissions.IsAuthenticated])
router = DefaultRouter()
router.register(r"persons", views.PersonViewSet, basename="person")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("docs/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger"),
    path("api/v1/", include(router.urls)),
    # path("api/v1/", include("accounts.urls")),
]
